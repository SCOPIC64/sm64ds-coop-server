param(
    [string]$LobbyUrl,
    [Parameter(Mandatory=$true)][string]$RelayAddress,
    [string]$GameFolder,
    [string]$DiscoveryKey,
    [switch]$LocalTest,
    [string]$TestAppDataRoot
)
$ErrorActionPreference='Stop'
if($LobbyUrl){
    $taskLobby=[Uri]$LobbyUrl
    $taskLocal=$LocalTest -and $taskLobby.Scheme -eq 'http' -and $taskLobby.Host -eq '127.0.0.1'
    if((($taskLobby.Scheme -ne 'https') -and !$taskLocal) -or $taskLobby.AbsolutePath -ne '/' -or $taskLobby.Query -or $taskLobby.Fragment -or $taskLobby.UserInfo){throw 'Use the HTTPS origin of the public relay host'}
}
if($RelayAddress -notmatch '^[A-Za-z0-9.-]+:([0-9]{1,5})$' -or [int]$Matches[1] -lt 1 -or [int]$Matches[1] -gt 65535){throw 'Use relay-hostname:UDP-port'}
$taskProfileData=@{relay_addr=$RelayAddress}
if($DiscoveryKey){
    $taskPublicKey=[Convert]::FromBase64String($DiscoveryKey)
    if($taskPublicKey.Length -ne 276 -or $taskPublicKey[0] -ne 6 -or [Text.Encoding]::ASCII.GetString($taskPublicKey,8,4) -ne 'RSA1'){throw 'Use the server discovery public key, never a private key'}
    $taskProfileData.discovery_key=$DiscoveryKey
} elseif($LobbyUrl){$taskProfileData.lobby_url=$taskLobby.GetLeftPart([UriPartial]::Authority)}
else {throw 'Supply a lobby URL or the server discovery public key'}
$taskProfile=$taskProfileData|ConvertTo-Json -Compress
if($LobbyUrl){
    $taskHealthUrl=$taskLobby.GetLeftPart([UriPartial]::Authority)+'/port/lobby/health'
    $taskHealth=Invoke-RestMethod -Uri $taskHealthUrl -TimeoutSec 15
    if(!$taskHealth.ok -or $taskHealth.contract_v -lt 4 -or $taskHealth.dial_max -ne 7){throw 'The server must be online with contract 4 and a seven-player limit'}
}
Add-Type -AssemblyName System.Security
$taskBytes=[Text.Encoding]::UTF8.GetBytes($taskProfile)
$taskEncrypted=[Security.Cryptography.ProtectedData]::Protect($taskBytes,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
$taskAppDataRoot=[Environment]::GetFolderPath('ApplicationData')
if($TestAppDataRoot){if(!$LocalTest){throw 'TestAppDataRoot requires LocalTest'};$taskAppDataRoot=$TestAppDataRoot}
$taskFolder=Join-Path $taskAppDataRoot 'SM64DS-Coop'
New-Item -ItemType Directory -Path $taskFolder -Force | Out-Null
$taskPath=Join-Path $taskFolder 'server.txt'
if(Test-Path -LiteralPath $taskPath){Copy-Item -LiteralPath $taskPath -Destination ($taskPath+'.backup') -Force}
[IO.File]::WriteAllText($taskPath,[Convert]::ToBase64String($taskEncrypted),[Text.Encoding]::ASCII)
[Array]::Clear($taskBytes,0,$taskBytes.Length)
if($GameFolder){
    $taskGamePath=(Resolve-Path -LiteralPath $GameFolder).Path
    if(!(Test-Path -LiteralPath (Join-Path $taskGamePath 'sm64ds coop.exe'))){throw 'Game folder does not contain sm64ds coop.exe'}
    # Distribution profile contains only the public relay address, never a
    # home address. The game encrypts it separately for each Windows user.
    [IO.File]::WriteAllText((Join-Path $taskGamePath 'server-profile.json'),$taskProfile,[Text.UTF8Encoding]::new($false))
}
Write-Output 'Encrypted AppData server profile installed. Open the game and choose Host or Join.'
