# Domain DPAPI Backup Key Extraction

## Metadata


|               |    |
|:--------------|:---|
| id            | WIN-190620024610 |
| author        | Roberto Rodriguez @Cyb3rWard0g |
| creation date | 2019/06/20 |
| platform      | Windows |
| playbook link |  |
        

## Technical Description
Starting with Microsoft® Windows® 2000, the operating system began to provide a data protection application-programming interface (API).
This Data Protection API (DPAPI) is a pair of function calls (CryptProtectData / CryptUnprotectData) that provide operating system-level data protection services to user and system processes.
DPAPI initially generates a strong key called a MasterKey, which is protected by the user's password. DPAPI uses a standard cryptographic process called Password-Based Key Derivation to generate a key from the password.
This password-derived key is then used with Triple-DES to encrypt the MasterKey, which is finally stored in the user's profile directory.

When a computer is a member of a domain, DPAPI has a backup mechanism to allow unprotection of the data. When a MasterKey is generated, DPAPI talks to a Domain Controller.
Domain Controllers have a domain-wide public/private key pair, associated solely with DPAPI. The local DPAPI client gets the Domain Controller public key from a Domain Controller by using a mutually authenticated and privacy protected RPC call. The client encrypts the MasterKey with the Domain Controller public key. It then stores this backup MasterKey along with the MasterKey protected by the user's password.
If an adversary obtains domain admin (or equivalent) privileges, the domain backup key can be stolen and used to decrypt any domain user master key.
Tools such as Mimikatz with the method/module lsadump::backupkeys can be used to extract the domain backup key.
It uses the LsaOpenPolicy/LsaRetrievePrivateData API calls (instead of MS-BKRP) to retrieve the value for the G$BCKUPKEY_PREFERRED and G$BCKUPKEY_P LSA secrets.

Additional reading
* https://github.com/OTRF/ThreatHunter-Playbook/tree/master/docs/library/data_protection_api.md
* https://github.com/OTRF/ThreatHunter-Playbook/tree/master/docs/library/lsa_policy_objects.md

## Hypothesis
Adversaries might be extracting the DPAPI domain backup key from my DC to be able to decrypt any domain user master key files.

## Analytics

### Initialize Analytics Engine

from openhunt.mordorutils import *
spark = get_spark()

### Download & Process Mordor File

mordor_file = "https://raw.githubusercontent.com/OTRF/mordor/master/datasets/small/windows/credential_access/empire_mimikatz_export_master_key.tar.gz"
registerMordorSQLTable(spark, mordor_file, "mordorTable")

### Analytic I


| FP Rate  | Log Channel | Description   |
| :--------| :-----------| :-------------|
| Low       | ['Security']          | Monitor for any SecretObject with the string BCKUPKEY in the ObjectName            |
            

df = spark.sql(
    '''
SELECT `@timestamp`, computer_name, ObjectServer, ObjectType, ObjectName
FROM mordorTable
WHERE channel = "Security"
    AND event_id = 4662
    AND AccessMask = "0x2"
    AND lower(ObjectName) LIKE "%bckupkey%"
    '''
)
df.show(10,False)

### Analytic II


| FP Rate  | Log Channel | Description   |
| :--------| :-----------| :-------------|
| Low       | ['Security']          | We can get the user logon id of the user that accessed the *bckupkey* object and JOIN it with a successful logon event (4624) user logon id to find the source IP            |
            

df = spark.sql(
    '''
SELECT o.`@timestamp`, o.computer_name, o.ObjectName, a.IpAddress
FROM mordorTable o
INNER JOIN (
    SELECT computer_name,TargetUserName,TargetLogonId,IpAddress
    FROM mordorTable
    WHERE channel = "Security"
        AND LogonType = 3
        AND IpAddress is not null
        AND NOT TargetUserName LIKE "%$"
    ) a
ON o.SubjectLogonId = a.TargetLogonId
WHERE channel = "Security"
    AND o.event_id = 4662
    AND o.AccessMask = "0x2"
    AND lower(o.ObjectName) LIKE "%bckupkey%"
    AND o.computer_name = a.computer_name
    '''
)
df.show(10,False)

### Analytic III


| FP Rate  | Log Channel | Description   |
| :--------| :-----------| :-------------|
| Low       | ['Security']          | Monitoring for access to the protected_storage service is very interesting to document potential DPAPI activity over the network            |
            

df = spark.sql(
    '''
SELECT `@timestamp`, computer_name, SubjectUserName, ShareName, RelativeTargetName, AccessMask, IpAddress
FROM mordorTable
WHERE channel = "Security"
    AND event_id = 5145
    AND ShareName LIKE "%IPC%"
    AND RelativeTargetName = "protected_storage"
    '''
)
df.show(10,False)

### Analytic IV


| FP Rate  | Log Channel | Description   |
| :--------| :-----------| :-------------|
| Low       | ['Security']          | This event generates every time that a backup is attempted for the DPAPI Master Key. When a computer is a member of a domain, DPAPI has a backup mechanism to allow unprotection of the data. When a Master Key is generated, DPAPI communicates with a domain controller.            |
            

df = spark.sql(
    '''
SELECT `@timestamp`, computer_name, SubjectUserName, MasterKeyId, RecoveryKeyId
FROM mordorTable
WHERE channel = "Security"
    AND event_id = 4692
    '''
)
df.show(10,False)

## Detection Blindspots


## Hunter Notes
* Backup key can be displayed as base64 blob or exported as a .pvk file on disk (Mimikatz-like)
* Windows security event 4692 (Backup of data protection master key was attempted) also generates every time a new DPAPI Master Key is generated
* When a computer is a member of a domain, DPAPI has a backup mechanism to allow unprotection of the data. When a Master Key is generated, DPAPI communicates with a domain controller.

## Hunt Output

| Category | Type | Name     |
| :--------| :----| :--------|
| signature | SIGMA | [win_dpapi_domain_backupkey_extraction](https://github.com/OTRF/ThreatHunter-Playbook/tree/master/signatures/sigma/win_dpapi_domain_backupkey_extraction.yml) |
| signature | SIGMA | [win_protected_storage_service_access](https://github.com/OTRF/ThreatHunter-Playbook/tree/master/signatures/sigma/win_protected_storage_service_access.yml) |
| signature | SIGMA | [win_dpapi_domain_masterkey_backup_attempt](https://github.com/OTRF/ThreatHunter-Playbook/tree/master/signatures/sigma/win_dpapi_domain_masterkey_backup_attempt.yml) |

## References
* https://www.harmj0y.net/blog/redteaming/operational-guidance-for-offensive-user-dpapi-abuse/
* https://digital-forensics.sans.org/summit-archives/dfirprague14/Give_Me_the_Password_and_Ill_Rule_the_World_Francesco_Picasso.pdf
* https://docs.microsoft.com/en-us/windows/desktop/devnotes/pstore
* https://github.com/gentilkiwi/mimikatz/blob/641a3b29acd326d07269300d94dceafea041f760/mimikatz/modules/kuhl_m_lsadump.c#L1907
* https://github.com/GhostPack/SharpDPAPI/blob/6388040a92e59fc0d5a82b4ec31599aa6778fd3b/SharpDPAPI/lib/Backup.cs#L43
* https://github.com/gentilkiwi/mimikatz/blob/641a3b29acd326d07269300d94dceafea041f760/mimikatz/modules/kuhl_m_lsadump.c#L1906-L1926
* https://github.com/gentilkiwi/mimikatz/blob/641a3b29acd326d07269300d94dceafea041f760/mimikatz/modules/kuhl_m_lsadump.c#L1758
* https://docs.microsoft.com/en-us/openspecs/windows_protocols/ms-lsad/88c6bd18-6c40-4a82-ae19-fe7bfec5108b