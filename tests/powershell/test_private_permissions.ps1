$ErrorActionPreference = 'Stop'
$taskHelper = Join-Path $PSScriptRoot '..\..\scripts\protect_private_workspace.ps1'
$taskTemporary = Join-Path ([IO.Path]::GetTempPath()) ('applicator-acl-test-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $taskTemporary

function New-TestWorkspace([string]$Name) {
    $taskFixture = Join-Path $taskTemporary $Name
    $null = New-Item -ItemType Directory -Path (Join-Path $taskFixture 'src\applicator') -Force
    'fictional project' | Set-Content -LiteralPath (Join-Path $taskFixture 'pyproject.toml')
    return $taskFixture
}
function Assert-Private([string]$Path) {
    $taskAllowed = @(
        [Security.Principal.WindowsIdentity]::GetCurrent().User.Value,
        'S-1-5-18', 'S-1-5-32-544'
    )
    $taskAcl = Get-Acl -LiteralPath $Path
    foreach ($taskRule in $taskAcl.Access) {
        if ($taskRule.AccessControlType -eq 'Allow' -and
            $taskRule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -notin $taskAllowed) {
            throw 'An unexpected principal retained access to a private fixture.'
        }
    }
}
function Get-ComparableDacl([string]$Sddl) {
    $taskDescriptor = [Security.AccessControl.RawSecurityDescriptor]::new($Sddl)
    # Set-Acl normalises this automatic bookkeeping flag even when all permissions match.
    # Retain every ACE/mask/order/inheritance flag and the DACL protection state.
    $taskDescriptor.SetFlags($taskDescriptor.ControlFlags -band
        (-bnot [Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInherited))
    return $taskDescriptor.GetSddlForm([Security.AccessControl.AccessControlSections]::Access)
}
try {
    $taskFixture = New-TestWorkspace 'ordinary'
    $taskSource = Join-Path $taskFixture 'src\applicator\fictional.py'
    $taskExample = Join-Path $taskFixture '.env.example'
    'public source' | Set-Content -LiteralPath $taskSource
    'PUBLIC_SAMPLE=true' | Set-Content -LiteralPath $taskExample
    $taskSourceAcl = (Get-Acl -LiteralPath $taskSource).Sddl
    $taskExampleAcl = (Get-Acl -LiteralPath $taskExample).Sddl
    $null = New-Item -ItemType Directory -Path (Join-Path $taskFixture 'data\nested') -Force
    $taskFile = Join-Path $taskFixture 'data\nested\fictional.txt'
    'fictional private content' | Set-Content -LiteralPath $taskFile
    'FICTIONAL_VALUE=true' | Set-Content -LiteralPath (Join-Path $taskFixture '.env')
    'FICTIONAL_OTHER=true' | Set-Content -LiteralPath (Join-Path $taskFixture '.env.test')
    'FICTIONAL_UPPER=true' | Set-Content -LiteralPath (Join-Path $taskFixture '.ENV.OTHER')
    $taskHash = (Get-FileHash -LiteralPath $taskFile).Hash
    $taskOriginalOwner = (Get-Acl -LiteralPath $taskFile).Owner
    $taskAcl = Get-Acl -LiteralPath $taskFile
    $taskAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        [Security.Principal.SecurityIdentifier]::new('S-1-1-0'), 'Read', 'Allow'
    ))
    Set-Acl -LiteralPath $taskFile -AclObject $taskAcl
    & $taskHelper -WorkspaceRoot $taskFixture
    foreach ($taskPath in @('data','data\nested','data\nested\fictional.txt','.env','.env.test','.ENV.OTHER','tmp')) {
        Assert-Private (Join-Path $taskFixture $taskPath)
    }
    if ((Get-FileHash -LiteralPath $taskFile).Hash -ne $taskHash -or
        (Get-Acl -LiteralPath $taskFile).Owner -ne $taskOriginalOwner -or
        (Get-Acl -LiteralPath $taskSource).Sddl -ne $taskSourceAcl -or
        (Get-Acl -LiteralPath $taskExample).Sddl -ne $taskExampleAcl) {
        throw 'Protection changed file content or public-source permissions.'
    }
    $taskBackup = Get-ChildItem -LiteralPath (Join-Path $taskFixture 'tmp') -Filter 'private-acl-before-*.json'
    if (@($taskBackup).Count -ne 1) { throw 'Expected one prior-DACL backup.' }
    Assert-Private $taskBackup.FullName
    $taskRows = Get-Content -LiteralPath $taskBackup.FullName -Raw | ConvertFrom-Json
    if (-not ($taskRows | Where-Object Path -eq $taskFile)) { throw 'Private file DACL missing from backup.' }
    & $taskHelper -WorkspaceRoot $taskFixture
    Assert-Private $taskFile

    $taskLinked = New-TestWorkspace 'linked'
    $taskOutside = Join-Path $taskTemporary 'outside'
    $null = New-Item -ItemType Directory -Path $taskOutside
    $null = New-Item -ItemType Directory -Path (Join-Path $taskLinked 'data')
    $null = New-Item -ItemType Junction -Path (Join-Path $taskLinked 'data\escape') -Target $taskOutside
    $taskOutsideAcl = (Get-Acl -LiteralPath $taskOutside).Sddl
    $taskRefused = $false
    try { & $taskHelper -WorkspaceRoot $taskLinked } catch { $taskRefused = $_.Exception.Message -match 'Reparse points' }
    if (-not $taskRefused -or (Get-Acl -LiteralPath $taskOutside).Sddl -ne $taskOutsideAcl) {
        throw 'Reparse-point protection failed or changed an outside DACL.'
    }
    # Remove only the junction itself before recursively cleaning the verified temporary tree.
    [IO.Directory]::Delete((Join-Path $taskLinked 'data\escape'))
    $taskEmpty = New-TestWorkspace 'empty'
    & $taskHelper -WorkspaceRoot $taskEmpty
    if (Test-Path -LiteralPath (Join-Path $taskEmpty 'tmp')) { throw 'Empty workspace was changed.' }
    $taskRefused = $false
    try { & $taskHelper -WorkspaceRoot $taskOutside } catch { $taskRefused = $_.Exception.Message -match 'Expected an Autonomous' }
    if (-not $taskRefused) { throw 'Non-project path was accepted.' }
    $taskDefault = New-TestWorkspace 'default'
    $null = New-Item -ItemType Directory -Path (Join-Path $taskDefault 'scripts')
    $taskCopiedHelper = Join-Path $taskDefault 'scripts\protect_private_workspace.ps1'
    Copy-Item -LiteralPath $taskHelper -Destination $taskCopiedHelper
    'FICTIONAL_VALUE=true' | Set-Content -LiteralPath (Join-Path $taskDefault '.env')
    & $taskCopiedHelper
    Assert-Private (Join-Path $taskDefault '.env')
    $taskRollback = New-TestWorkspace 'rollback'
    $null = New-Item -ItemType Directory -Path (Join-Path $taskRollback 'data')
    $taskRollbackFile = Join-Path $taskRollback 'data\fictional.txt'
    'fictional rollback content' | Set-Content -LiteralPath $taskRollbackFile
    $taskFailPath = Join-Path $taskRollback '.env'
    'FICTIONAL_VALUE=true' | Set-Content -LiteralPath $taskFailPath
    # Reproduce a legacy descriptor without AI metadata, as seen on hosted Windows runners.
    # This native setter is fixture-only; the production helper uses Set-Acl.
    if (-not ('ApplicatorLegacyAclFixture' -as [type])) {
        Add-Type @'
using System.Runtime.InteropServices;
public static class ApplicatorLegacyAclFixture {
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetFileSecurity(string path, uint sections, byte[] descriptor);
}
'@
    }
    $taskLegacyAcl = Get-ComparableDacl ((Get-Acl -LiteralPath $taskFailPath).GetSecurityDescriptorSddlForm(
        [Security.AccessControl.AccessControlSections]::Access
    ))
    $taskLegacyDescriptor = [Security.AccessControl.RawSecurityDescriptor]::new($taskLegacyAcl)
    $taskBinary = [byte[]]::new($taskLegacyDescriptor.BinaryLength)
    $taskLegacyDescriptor.GetBinaryForm($taskBinary, 0)
    if (-not [ApplicatorLegacyAclFixture]::SetFileSecurity($taskFailPath, 4, $taskBinary)) {
        throw 'Legacy fictional DACL setup failed.'
    }
    $taskObservedLegacy = [Security.AccessControl.RawSecurityDescriptor]::new(
        (Get-Acl -LiteralPath $taskFailPath).GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access)
    )
    if ($taskObservedLegacy.ControlFlags -band [Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInherited) {
        throw 'The legacy fixture unexpectedly acquired auto-inheritance metadata.'
    }
    $taskPrior = @{}
    foreach ($taskPath in @((Join-Path $taskRollback 'data'), $taskRollbackFile, $taskFailPath)) {
        $taskPrior[$taskPath] = (Get-Acl -LiteralPath $taskPath).GetSecurityDescriptorSddlForm(
            [Security.AccessControl.AccessControlSections]::Access
        )
    }
    $taskFaultState = @{Used = $false}
    function Set-Acl {
        param([string]$LiteralPath, [object]$AclObject)
        if ($LiteralPath -eq $taskFailPath -and -not $taskFaultState.Used) {
            $taskFaultState.Used = $true
            throw 'Fictional ACL write failure.'
        }
        Microsoft.PowerShell.Security\Set-Acl -LiteralPath $LiteralPath -AclObject $AclObject
    }
    $taskRefused = $false
    try { & $taskHelper -WorkspaceRoot $taskRollback } catch { $taskRefused = $_.Exception.Message -match 'Fictional ACL write failure' }
    Remove-Item Function:\Set-Acl
    if (-not $taskRefused -or -not $taskFaultState.Used) { throw 'The ACL fault was not propagated.' }
    foreach ($taskPath in $taskPrior.Keys) {
        $taskCurrentDacl = (Get-Acl -LiteralPath $taskPath).GetSecurityDescriptorSddlForm(
            [Security.AccessControl.AccessControlSections]::Access
        )
        if ((Get-ComparableDacl $taskCurrentDacl) -ne (Get-ComparableDacl $taskPrior[$taskPath])) {
            throw 'Original access rules or their protection state were not restored.'
        }
    }
    # The comparator must still detect real changes to access masks or protection.
    $taskChanged = [Security.AccessControl.RawSecurityDescriptor]::new($taskLegacyAcl)
    $taskChanged.DiscretionaryAcl[0].AccessMask = $taskChanged.DiscretionaryAcl[0].AccessMask -bxor 1
    if ((Get-ComparableDacl $taskChanged.GetSddlForm([Security.AccessControl.AccessControlSections]::Access)) -eq
        (Get-ComparableDacl $taskLegacyAcl)) { throw 'An access-mask change was ignored.' }
    $taskChanged = [Security.AccessControl.RawSecurityDescriptor]::new($taskLegacyAcl)
    $taskChanged.SetFlags($taskChanged.ControlFlags -bxor [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected)
    if ((Get-ComparableDacl $taskChanged.GetSddlForm([Security.AccessControl.AccessControlSections]::Access)) -eq
        (Get-ComparableDacl $taskLegacyAcl)) { throw 'A protection-state change was ignored.' }
    Write-Output 'Eight Windows ACL scenarios passed, including legacy metadata rollback and comparator rejection of changed permissions.'
} finally {
    $taskResolved = [IO.Path]::GetFullPath($taskTemporary)
    $taskTempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $taskResolved.StartsWith($taskTempPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not ([IO.Path]::GetFileName($taskResolved)).StartsWith('applicator-acl-test-')) {
        throw 'Refusing to clean an unverified temporary path.'
    }
    Remove-Item -LiteralPath $taskResolved -Recurse -Force
}
