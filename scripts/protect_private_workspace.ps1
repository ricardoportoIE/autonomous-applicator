[CmdletBinding()]
param([string]$WorkspaceRoot = '')

$ErrorActionPreference = 'Stop'
if (-not $WorkspaceRoot) { $WorkspaceRoot = Join-Path $PSScriptRoot '..' }
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Private workspace ACL protection requires Windows.'
}
$taskRoot = (Get-Item -LiteralPath $WorkspaceRoot -Force).FullName.TrimEnd('\')
if (-not (Test-Path -LiteralPath (Join-Path $taskRoot 'pyproject.toml') -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $taskRoot 'src\applicator') -PathType Container)) {
    throw 'Expected an Autonomous Applicator workspace.'
}
if ((Get-Item -LiteralPath $taskRoot -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw 'Reparse points are not supported for private workspace paths.'
}
$taskPrefix = $taskRoot + '\'
$taskTargets = @()
foreach ($taskName in @('data', 'tmp', 'output')) {
    $taskPath = Join-Path $taskRoot $taskName
    if (Test-Path -LiteralPath $taskPath) { $taskTargets += Get-Item -LiteralPath $taskPath -Force }
}
$taskTargets += Get-ChildItem -LiteralPath $taskRoot -Force -File | Where-Object {
    ($_.Name -eq '.env' -or $_.Name.StartsWith('.env.', [StringComparison]::OrdinalIgnoreCase)) -and $_.Name -ne '.env.example'
}

# Inspect every path and retain its prior DACL before changing anything. Never follow links.
$taskPlan = [Collections.Generic.List[object]]::new()
$taskPending = [Collections.Generic.Queue[object]]::new()
foreach ($taskItem in $taskTargets) { $taskPending.Enqueue($taskItem) }
while ($taskPending.Count -gt 0) {
    $taskItem = $taskPending.Dequeue()
    $taskPath = [IO.Path]::GetFullPath($taskItem.FullName)
    if (-not $taskPath.StartsWith($taskPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        ($taskItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Reparse points or escaping private paths are not supported.'
    }
    $taskAcl = Get-Acl -LiteralPath $taskPath
    $taskPlan.Add([pscustomobject]@{
        Path = $taskPath
        Directory = $taskItem.PSIsContainer
        Dacl = $taskAcl.GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access)
    })
    if ($taskItem.PSIsContainer) {
        foreach ($taskChild in Get-ChildItem -LiteralPath $taskPath -Force) {
            $taskPending.Enqueue($taskChild)
        }
    }
}
if ($taskPlan.Count -eq 0) {
    Write-Output 'No private workspace paths exist yet.'
    return
}

$taskBackupDirectory = Join-Path $taskRoot 'tmp'
$taskBackupExisted = Test-Path -LiteralPath $taskBackupDirectory
if (-not $taskBackupExisted) {
    $null = New-Item -ItemType Directory -Path $taskBackupDirectory
    $taskBackupAcl = Get-Acl -LiteralPath $taskBackupDirectory
    $taskPlan.Add([pscustomobject]@{
        Path = $taskBackupDirectory
        Directory = $true
        Dacl = $taskBackupAcl.GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access)
    })
}
$taskBackup = Join-Path $taskBackupDirectory ('private-acl-before-' + [Guid]::NewGuid().ToString('N') + '.json')
$taskPlan | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $taskBackup -Encoding UTF8
$taskAccount = [Security.Principal.WindowsIdentity]::GetCurrent().User
$taskPrincipals = @(
    $taskAccount,
    [Security.Principal.SecurityIdentifier]::new('S-1-5-18'),
    [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
)

try {
    foreach ($taskEntry in $taskPlan) {
        if ($taskEntry.Directory) {
            $taskAcl = [Security.AccessControl.DirectorySecurity]::new()
            $taskInheritance = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
        } else {
            $taskAcl = [Security.AccessControl.FileSecurity]::new()
            $taskInheritance = [Security.AccessControl.InheritanceFlags]::None
        }
        $taskAcl.SetAccessRuleProtection($true, $false)
        foreach ($taskPrincipal in $taskPrincipals) {
            $taskRule = [Security.AccessControl.FileSystemAccessRule]::new(
                $taskPrincipal,
                [Security.AccessControl.FileSystemRights]::FullControl,
                $taskInheritance,
                [Security.AccessControl.PropagationFlags]::None,
                [Security.AccessControl.AccessControlType]::Allow
            )
            $taskAcl.AddAccessRule($taskRule)
        }
        Set-Acl -LiteralPath $taskEntry.Path -AclObject $taskAcl
    }
    # The new backup file inherits only the now-protected tmp directory's permissions.
    $taskBackupAcl = Get-Acl -LiteralPath $taskBackup
    foreach ($taskRule in $taskBackupAcl.Access) {
        if ($taskRule.AccessControlType -eq 'Allow' -and
            $taskRule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]) -notin $taskPrincipals) {
            throw 'The ACL backup did not inherit private permissions.'
        }
    }
} catch {
    # Restore prior DACLs if protection fails. The backup supports manual recovery too.
    foreach ($taskEntry in $taskPlan) {
        $taskAcl = Get-Acl -LiteralPath $taskEntry.Path
        $taskAcl.SetSecurityDescriptorSddlForm($taskEntry.Dacl, [Security.AccessControl.AccessControlSections]::Access)
        Set-Acl -LiteralPath $taskEntry.Path -AclObject $taskAcl
    }
    throw
}
Write-Output ('Protected {0} private paths. Prior DACLs saved under tmp; source files unchanged.' -f $taskPlan.Count)
