import tomllib

from pydantic import BaseModel
from typing import List, Dict
from functools import cache
import uuid
from datetime import datetime, timedelta
import time
from directories import FILE_CONFIG
from ioc import IoCLink


class Org(BaseModel):
    name: str
    uuid: str
    email: str


class MISPFeed(BaseModel):
    manifest: dict
    events: List[dict]


@cache
def get_org() -> Org:
    with open(FILE_CONFIG, 'rb') as f:
        return Org.model_validate(tomllib.load(f)["misp-org"])


def fake_uuid(data: bytes) -> str:
    """
    Creates UUID from input data using UUID5 (name-based UUID using SHA-1).
    :param data: Input data to hash.
    :return: UUID string.
    """
    # Use UUID5 with a custom namespace to generate deterministic but valid UUIDs
    namespace = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')  # DNS namespace
    return str(uuid.uuid5(namespace, data))


def generate_misp_feed(iocs: List[IoCLink]) -> MISPFeed:
    """
    Generate a MISP feed from a list of IoCs
    :param iocs: List of IoCs to include in the feed
    :return: MISPFeed object containing the manifest and events
    """

    posts: Dict[str, List[IoCLink]] = {}
    for ioc in iocs:
        for link in ioc['links']:
            if link not in posts:
                posts[link] = []
            posts[link].append(ioc)
    events = []
    for post_url, iocs_list in posts.items():
        event = generate_misp_compatible_json(post_url, iocs_list)
        events.append(event)
    manifest = generate_misp_manifest_json(events)
    return MISPFeed(manifest=manifest, events=events)


def generate_misp_compatible_json(post_url: str, iocs: List[IoCLink]) -> dict:
    """Convert the Record to a MISP-compatible JSON format"""

    org = get_org()
    # Generate unique IDs for this event
    event_uuid = fake_uuid(org.uuid.encode() + b'-event-' + post_url.encode('utf-8'))

    event_date = datetime.fromtimestamp(int(time.time()))

    # Create MISP Event structure
    misp_event = {
        "Event": {
            "uuid": event_uuid,
            "info": f"uCTI - {post_url}",
            "date": event_date.strftime("%Y-%m-%d"),
            "timestamp": event_date.timestamp(),
            "published": True,
            "analysis": 1 if datetime.now() - event_date < timedelta(days=7) else 2,  # 0=Initial, 1=Ongoing, 2=Complete
            "threat_level_id": 4,  # 1=High, 2=Medium, 3=Low, 4=Undefined
            "distribution": 3,  # 0=Your org only, 1=This community, 2=Connected communities, 3=All communities
            "event_creator_email": org.email,
            "Orgc": {
                "name": org.name,
                "uuid": org.uuid
            },
            "Tag": [
                {
                    "name": "type:OSINT",
                    "colour": "#004646",
                    "exportable": True,
                    "hide_tag": False
                },
                {
                    "name": "tlp:white",
                    "colour": "#ffffff",
                    "exportable": True,
                    "hide_tag": False
                }
            ],
            "Attribute": []
        }
    }

    # Convert IOCs to MISP Attributes
    for ioc in iocs:
        attribute = {
            "uuid": fake_uuid(b'ioc-' + post_url.encode() + b'-' + ioc['type'].encode('utf-8') + b'-' + (ioc.get('subtype') or '').encode('utf8') + b'-' + ioc['value'].encode('utf-8')),
            "type": ioc['type'],
            "category": _get_category_for_type(ioc['type']),
            "to_ids": False,
            "timestamp": event_date.timestamp(),
            "value": ioc['value'],
            "comment": ioc['comment'],
            "distribution": 3
        }

        misp_event["Event"]["Attribute"].append(attribute)

    # Add a reference to the source URL as a MISP Attribute
    misp_event["Event"]["Attribute"].append({
        "uuid": str(uuid.uuid4()),
        "type": "link",
        "category": "External analysis",
        "to_ids": False,
        "timestamp": int(time.time()),
        "value": post_url,
        "comment": f"Source URL for the threat intel",
        "distribution": 3,
        "disable_correlation": True
    })

    return misp_event


def generate_misp_manifest_json(misp_events: List[dict]) -> dict:
    """Generate a MISP manifest.json from a list of MISP event JSON strings"""
    manifest = {}

    for event_data in misp_events:
        # Parse the MISP event JSON
        event = event_data.get("Event", {})

        # Extract the UUID as the key
        event_uuid = event.get("uuid")
        if not event_uuid:
            continue

        # Create manifest entry with required fields
        org = get_org()

        manifest[event_uuid] = {
            "info": event.get("info", ""),
            "date": event.get("date", ""),
            "analysis": event.get("analysis", 1),
            "threat_level_id": event.get("threat_level_id", 2),
            "timestamp": event.get("timestamp", int(time.time())),
            "Orgc": event.get("Orgc", {
                "name": org.name,
                "uuid": org.uuid
            }),
            "Tag": event.get("Tag", [])
        }

    return manifest


def _get_category_for_type(ioc_type: str) -> str:
    """Map IOC types to appropriate MISP categories"""
    category_mapping = {
        # Hash types - Artifacts dropped
        "md5": "Artifacts dropped",
        "sha1": "Artifacts dropped",
        "sha224": "Artifacts dropped",
        "sha256": "Artifacts dropped",
        "sha384": "Artifacts dropped",
        "sha512": "Artifacts dropped",
        "sha512/224": "Artifacts dropped",
        "sha512/256": "Artifacts dropped",
        "sha3-224": "Artifacts dropped",
        "sha3-256": "Artifacts dropped",
        "sha3-384": "Artifacts dropped",
        "sha3-512": "Artifacts dropped",
        "ssdeep": "Artifacts dropped",
        "imphash": "Artifacts dropped",
        "telfhash": "Artifacts dropped",
        "impfuzzy": "Artifacts dropped",
        "authentihash": "Artifacts dropped",
        "vhash": "Artifacts dropped",
        "cdhash": "Artifacts dropped",
        "pehash": "Payload delivery",
        "tlsh": "Payload delivery",

        # Filename with hash - Artifacts dropped
        "filename|md5": "Artifacts dropped",
        "filename|sha1": "Artifacts dropped",
        "filename|sha224": "Artifacts dropped",
        "filename|sha256": "Artifacts dropped",
        "filename|sha384": "Artifacts dropped",
        "filename|sha512": "Artifacts dropped",
        "filename|sha512/224": "Artifacts dropped",
        "filename|sha512/256": "Artifacts dropped",
        "filename|sha3-224": "Artifacts dropped",
        "filename|sha3-256": "Artifacts dropped",
        "filename|sha3-384": "Artifacts dropped",
        "filename|sha3-512": "Artifacts dropped",
        "filename|authentihash": "Artifacts dropped",
        "filename|vhash": "Artifacts dropped",
        "filename|ssdeep": "Artifacts dropped",
        "filename|tlsh": "Artifacts dropped",
        "filename|imphash": "Artifacts dropped",
        "filename|impfuzzy": "Artifacts dropped",
        "filename|pehash": "Artifacts dropped",

        # Network types - Network activity
        "ip-src": "Network activity",
        "ip-dst": "Network activity",
        "ip-dst|port": "Network activity",
        "ip-src|port": "Network activity",
        "port": "Network activity",
        "hostname": "Network activity",
        "domain": "Network activity",
        "domain|ip": "Network activity",
        "hostname|port": "Network activity",
        "mac-address": "Network activity",
        "mac-eui-64": "Network activity",
        "url": "Network activity",
        "uri": "Network activity",
        "user-agent": "Network activity",
        "http-method": "Network activity",
        "AS": "Network activity",

        # Email types - Network activity
        "email": "Network activity",
        "email-src": "Network activity",
        "email-dst": "Network activity",
        "email-subject": "Network activity",
        "eppn": "Network activity",

        # Email delivery types - Payload delivery
        "email-attachment": "Payload delivery",
        "email-body": "Payload delivery",
        "email-dst-display-name": "Payload delivery",
        "email-src-display-name": "Payload delivery",
        "email-header": "Payload delivery",
        "email-reply-to": "Payload delivery",
        "email-x-mailer": "Payload delivery",
        "email-mime-boundary": "Payload delivery",
        "email-thread-index": "Payload delivery",
        "email-message-id": "Payload delivery",

        # File types - Artifacts dropped
        "filename": "Artifacts dropped",
        "pdb": "Artifacts dropped",
        "named pipe": "Artifacts dropped",
        "mutex": "Artifacts dropped",
        "process-state": "Artifacts dropped",
        "windows-scheduled-task": "Artifacts dropped",
        "windows-service-name": "Artifacts dropped",
        "windows-service-displayname": "Artifacts dropped",

        # Registry - Persistence mechanism
        "regkey": "Persistence mechanism",
        "regkey|value": "Persistence mechanism",

        # Patterns - External analysis
        "pattern-in-file": "External analysis",
        "pattern-in-traffic": "External analysis",
        "pattern-in-memory": "External analysis",
        "filename-pattern": "External analysis",
        "yara": "External analysis",
        "sigma": "External analysis",
        "snort": "External analysis",
        "bro": "External analysis",
        "zeek": "External analysis",
        "stix2-pattern": "External analysis",

        # Certificates - External analysis
        "x509-fingerprint-sha1": "External analysis",
        "x509-fingerprint-md5": "External analysis",
        "x509-fingerprint-sha256": "External analysis",
        "ja3-fingerprint-md5": "External analysis",
        "jarm-fingerprint": "External analysis",
        "hassh-md5": "External analysis",
        "hasshserver-md5": "External analysis",

        # Vulnerabilities - External analysis
        "vulnerability": "External analysis",
        "cpe": "External analysis",
        "weakness": "External analysis",

        # Applications - Payload delivery
        "azure-application-id": "Payload delivery",
        "mobile-application-id": "Payload delivery",
        "chrome-extension-id": "Payload delivery",

        # Attribution
        "threat-actor": "Attribution",
        "campaign-name": "Attribution",
        "campaign-id": "Attribution",

        # WHOIS - Attribution
        "whois-registrant-phone": "Attribution",
        "whois-registrant-email": "Attribution",
        "whois-registrant-name": "Attribution",
        "whois-registrant-org": "Attribution",
        "whois-registrar": "Attribution",
        "whois-creation-date": "Attribution",
        "dns-soa-email": "Attribution",

        # Financial - Financial fraud
        "btc": "Financial fraud",
        "dash": "Financial fraud",
        "xmr": "Financial fraud",
        "iban": "Financial fraud",
        "bic": "Financial fraud",
        "bank-account-nr": "Financial fraud",
        "aba-rtn": "Financial fraud",
        "bin": "Financial fraud",
        "cc-number": "Financial fraud",
        "prtn": "Financial fraud",

        # Other network indicators - Network activity
        "community-id": "Network activity",
        "dom-hash": "Network activity",
        "onion-address": "Network activity",
        "favicon-mmh3": "Network activity",
        "dkim": "Network activity",
        "dkim-signature": "Network activity",
        "ssh-fingerprint": "Network activity",

        # Attachments and samples - Payload delivery
        "attachment": "Payload delivery",
        "malware-sample": "Payload delivery",
        "malware-type": "Payload delivery",
        "mime-type": "Payload delivery",

        # Generic types - Other
        "link": "External analysis",
        "comment": "Other",
        "text": "Other",
        "other": "Other",
        "hex": "Other",
        "size-in-bytes": "Other",
        "counter": "Other",
        "integer": "Other",
        "datetime": "Other",
        "float": "Other",
        "phone-number": "Other",
        "boolean": "Other",
        "anonymised": "Other",

        # Git and GitHub - External analysis / Internal reference
        "git-commit-id": "Internal reference",
        "github-username": "Social network",
        "github-repository": "External analysis",
        "github-organisation": "Social network",

        # Social and communication - Social network
        "jabber-id": "Social network",
        "twitter-id": "Social network",

        # Cookies - Network activity / Artifacts dropped
        "cookie": "Network activity",

        # PGP - Other
        "pgp-public-key": "Other",
        "pgp-private-key": "Other",

        # Targeting - Targeting data
        "target-user": "Targeting data",
        "target-email": "Targeting data",
        "target-machine": "Targeting data",
        "target-org": "Targeting data",
        "target-location": "Targeting data",
        "target-external": "Targeting data"
    }

    return category_mapping.get(ioc_type, "Other")
