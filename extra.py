import argparse
import base64
import csv
import datetime
import hashlib
import os
import platform
import re
import secrets
import sys
import uuid
import json
from pathlib import Path
import logging

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from flask import Flask, request, jsonify, render_template, send_from_directory, send_file

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("license_admin.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("license_admin")

# Constants
PRIVATE_KEY_PATH = Path("private_key.pem")
PUBLIC_KEY_PATH = Path("public_key.pem")
LICENSE_DB_PATH = Path("licenses.csv")
REACTIVATION_DB_PATH = Path("reactivation_requests.csv")

# License durations in days
LICENSE_DURATIONS = {
    "15d": 15,
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
    "lifetime": 0 
}

# Available license tiers and features
LICENSE_TIERS = {
    "basic": ["basic"],
    "premium": ["basic", "advanced", "export"],
    "professional": ["basic", "advanced", "export", "automation"],
    "enterprise": ["basic", "advanced", "export", "automation", "api", "priority-support"]
}

class LicenseManager:
    def __init__(self):
        self.private_key = None
        self.public_key = None
        self._ensure_license_db()
        
    def _ensure_key_pair(self):
        """Ensure that a key pair exists, creating one if necessary"""
        if not PRIVATE_KEY_PATH.exists() or not PUBLIC_KEY_PATH.exists():
            logger.info("Key pair not found. Generating new RSA key pair...")
            self._generate_key_pair()
        else:
            logger.info("Loading existing key pair")
            self.load_keys()
    
    def _generate_key_pair(self):
        """Generate a new RSA key pair for license signing"""
        try:
            # Generate private key
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048
            )
            
            # Extract public key
            public_key = private_key.public_key()
            
            # Save private key to file
            pem_private = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            
            with open(PRIVATE_KEY_PATH, 'wb') as f:
                f.write(pem_private)
            
            # Save public key to file
            pem_public = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            
            with open(PUBLIC_KEY_PATH, 'wb') as f:
                f.write(pem_public)
            
            self.private_key = private_key
            self.public_key = public_key
            logger.info("New RSA key pair generated and saved successfully")
            
            # Print a reminder about distributing the public key
            logger.info(f"Public key saved to {PUBLIC_KEY_PATH}. Distribute this file to clients.")
            
            return {"success": True, "message": "New RSA key pair generated successfully"}
        except Exception as e:
            logger.error(f"Error generating key pair: {e}")
            return {"success": False, "message": f"Error: {str(e)}"}
    
    def load_keys(self):
        """Load the RSA keys from files"""
        try:
            # Load private key
            if PRIVATE_KEY_PATH.exists():
                with open(PRIVATE_KEY_PATH, 'rb') as key_file:
                    self.private_key = serialization.load_pem_private_key(
                        key_file.read(),
                        password=None
                    )
            else:
                logger.error(f"Private key not found at {PRIVATE_KEY_PATH}")
                return False
            
            # Load public key
            if PUBLIC_KEY_PATH.exists():
                with open(PUBLIC_KEY_PATH, 'rb') as key_file:
                    self.public_key = serialization.load_pem_public_key(
                        key_file.read()
                    )
            else:
                logger.error(f"Public key not found at {PUBLIC_KEY_PATH}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error loading keys: {e}")
            return False
    
    def _ensure_license_db(self):
        """Create license database file if it doesn't exist"""
        if not LICENSE_DB_PATH.exists():
            with open(LICENSE_DB_PATH, 'w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([
                    "LicenseID", "CustomerID", "CustomerName", "Email", 
                    "HardwareID", "LicenseKey", "CreationDate", "ExpirationDate", 
                    "Tier", "Features", "Notes", "Status"
                ])
            logger.info(f"Created new license database at {LICENSE_DB_PATH}")
            
        # Create reactivation database if it doesn't exist
        if not REACTIVATION_DB_PATH.exists():
            with open(REACTIVATION_DB_PATH, 'w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([
                    "id", "license_key", "email", "old_hwid", "new_hwid", 
                    "timestamp", "reason", "status", "processed_date", "new_license_id"
                ])
            logger.info(f"Created new reactivation database at {REACTIVATION_DB_PATH}")
    
    def generate_license(self, hwid, duration, tier, customer_name, email, notes=""):
        """Generate a license key for a specific hardware ID and duration"""
        self._ensure_key_pair()
        
        # Generate unique IDs
        license_id = str(uuid.uuid4())
        customer_id = email.split('@')[0] + "-" + secrets.token_hex(4)
        
        # Determine expiration date
        now = datetime.datetime.now()
        creation_date = now.strftime("%Y-%m-%d")
        
        if duration == "lifetime":
            # For lifetime licenses, we'll set an expiration far in the future (100 years)
            expiration_timestamp = int((now + datetime.timedelta(days=36500)).timestamp())
            expiration_date = "Lifetime"
        else:
            # Calculate expiration based on duration
            days = LICENSE_DURATIONS.get(duration, 30)  # Default to 30 days if invalid duration
            expiration = now + datetime.timedelta(days=days)
            expiration_timestamp = int(expiration.timestamp())
            expiration_date = expiration.strftime("%Y-%m-%d")
        
        # Get features for the selected tier
        if tier in LICENSE_TIERS:
            features = ",".join(LICENSE_TIERS[tier])
        else:
            logger.warning(f"Invalid tier '{tier}'. Using 'basic' tier instead.")
            tier = "basic"
            features = ",".join(LICENSE_TIERS["basic"])
        
        # Format license data
        # Format: license_id|hwid|expiration|features|customer_id
        license_data = f"{license_id}|{hwid}|{expiration_timestamp}|{features}|{customer_id}"
        
        # Sign the license data
        try:
            signature = self.private_key.sign(
                license_data.encode(),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            # Encode license data and signature as base64
            encoded_data = base64.b64encode(license_data.encode()).decode('utf-8')
            encoded_signature = base64.b64encode(signature).decode('utf-8')
            
            # Format the license key
            license_key = f"{encoded_data}|{encoded_signature}"
            
            # Format the license key with dashes for readability (optional)
            formatted_key = self._format_key_for_display(license_key)
            
            # Store license in database
            self._store_license(
                license_id, customer_id, customer_name, email, hwid,
                license_key, creation_date, expiration_date, tier,
                features, notes
            )
            
            return {
                "license_id": license_id,
                "customer_id": customer_id,
                "hardware_id": hwid,
                "license_key": license_key,
                "formatted_key": formatted_key,
                "creation_date": creation_date,
                "expiration_date": expiration_date,
                "tier": tier,
                "features": features.split(","),
                "valid_until": expiration_date
            }
            
        except Exception as e:
            logger.error(f"Error generating license: {e}")
            return None
    
    def _format_key_for_display(self, key):
        """Format a license key with dashes for better readability"""
        # Replace any existing dashes or spaces
        key = re.sub(r'[\s-]', '', key)
        
        # Break up the key into chunks of 5 characters
        chunks = [key[i:i+5] for i in range(0, len(key), 5)]
        
        # Join chunks with dashes
        formatted = '-'.join(chunks)
        
        return formatted
    
    def _store_license(self, license_id, customer_id, customer_name, email, 
                      hwid, license_key, creation_date, expiration_date, 
                      tier, features, notes):
        """Store license information in the database"""
        try:
            with open(LICENSE_DB_PATH, 'a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([
                    license_id, customer_id, customer_name, email, 
                    hwid, license_key, creation_date, expiration_date, 
                    tier, features, notes, "active"
                ])
            logger.info(f"License stored in database: {license_id}")
            return True
        except Exception as e:
            logger.error(f"Error storing license in database: {e}")
            return False
    
    def process_reactivation(self, request_id, action):
        """Process a reactivation request (approve or reject)"""
        if not REACTIVATION_DB_PATH.exists():
            logger.error("Reactivation database does not exist")
            return False
        
        try:
            # Read the reactivation database
            reactivations = []
            target_request = None
            
            with open(REACTIVATION_DB_PATH, 'r', newline='') as file:
                reader = csv.DictReader(file)
                fieldnames = reader.fieldnames
                
                for row in reader:
                    if row.get('id', '') == request_id:
                        row['status'] = action
                        row['processed_date'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        target_request = row
                    reactivations.append(row)
            
            if not target_request:
                logger.error(f"Reactivation request with ID {request_id} not found")
                return False
            
            # Write the updated data back to the file
            with open(REACTIVATION_DB_PATH, 'w', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(reactivations)
            
            # If approved, generate a new license for the new hardware ID
            if action == "approved":
                # Look up the original license
                license_key = target_request.get('license_key', '')
                new_hwid = target_request.get('new_hwid', '')
                email = target_request.get('email', '')
                
                if not license_key or not new_hwid:
                    logger.error("Missing license key or new hardware ID in reactivation request")
                    return False
                
                # Find the original license details
                original_license = self._find_license_by_key(license_key)
                
                if not original_license:
                    logger.error(f"Original license not found for key: {license_key}")
                    return False
                
                # Generate a new license with the same parameters but new hardware ID
                new_license = self.generate_license(
                    hwid=new_hwid,
                    duration="lifetime" if original_license['ExpirationDate'] == "Lifetime" else "1y",  # Default to 1 year if not lifetime
                    tier=original_license['Tier'],
                    customer_name=original_license['CustomerName'],
                    email=email or original_license['Email'],
                    notes=f"Reactivation of license {original_license['LicenseID']} on {datetime.datetime.now().strftime('%Y-%m-%d')}"
                )
                
                # Mark the original license as reactivated
                self._update_license_status(original_license['LicenseID'], "reactivated")
                
                # Update the reactivation request with the new license ID
                for r in reactivations:
                    if r.get('id', '') == request_id:
                        r['new_license_id'] = new_license['license_id']
                
                # Write the updated reactivation data back to the file
                with open(REACTIVATION_DB_PATH, 'w', newline='') as file:
                    writer = csv.DictWriter(file, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(reactivations)
                
                logger.info(f"Reactivation request {request_id} approved and new license generated")
                return new_license
            else:
                logger.info(f"Reactivation request {request_id} marked as {action}")
                return True
                
        except Exception as e:
            logger.error(f"Error processing reactivation request: {e}")
            return False
    
    def _find_license_by_key(self, license_key):
        """Find a license in the database by its key"""
        try:
            with open(LICENSE_DB_PATH, 'r', newline='') as file:
                reader = csv.DictReader(file)
                
                for row in reader:
                    if row.get('LicenseKey', '') == license_key:
                        return row
            
            return None
        except Exception as e:
            logger.error(f"Error finding license: {e}")
            return None
    
    def _update_license_status(self, license_id, status):
        """Update the status of a license in the database"""
        try:
            licenses = []
            
            with open(LICENSE_DB_PATH, 'r', newline='') as file:
                reader = csv.DictReader(file)
                fieldnames = reader.fieldnames
                
                for row in reader:
                    if row.get('LicenseID', '') == license_id:
                        row['Status'] = status
                    licenses.append(row)
            
            with open(LICENSE_DB_PATH, 'w', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(licenses)
            
            logger.info(f"License {license_id} status updated to {status}")
            return True
        except Exception as e:
            logger.error(f"Error updating license status: {e}")
            return False
    
    def list_reactivation_requests(self, status=None):
        """List reactivation requests, optionally filtered by status"""
        if not REACTIVATION_DB_PATH.exists():
            logger.info("No reactivation requests found")
            return []
        
        try:
            requests = []
            
            with open(REACTIVATION_DB_PATH, 'r', newline='') as file:
                reader = csv.DictReader(file)
                
                for row in reader:
                    if status is None or row.get('status', '') == status:
                        requests.append(row)
            
            return requests
        except Exception as e:
            logger.error(f"Error listing reactivation requests: {e}")
            return []
    
    def list_licenses(self, status=None, expired=None, tier=None, search=None):
        """List licenses with various filter options"""
        if not LICENSE_DB_PATH.exists():
            logger.info("No licenses found")
            return []
        
        try:
            licenses = []
            today = datetime.datetime.now().date()
            
            with open(LICENSE_DB_PATH, 'r', newline='') as file:
                reader = csv.DictReader(file)
                
                for row in reader:
                    # Check status filter
                    if status is not None and status != "all" and row.get('Status', '').lower() != status.lower():
                        continue
                    
                    # Check tier filter
                    if tier is not None and tier != "all" and row.get('Tier', '').lower() != tier.lower():
                        continue
                    
                    # Check search filter
                    if search is not None and search != "":
                        search_lower = search.lower()
                        if (search_lower not in row.get('CustomerName', '').lower() and
                            search_lower not in row.get('Email', '').lower() and
                            search_lower not in row.get('LicenseID', '').lower() and
                            search_lower not in row.get('CustomerID', '').lower()):
                            continue
                    
                    # Check expiration filter
                    if expired is not None:
                        expiration_str = row.get('ExpirationDate', '')
                        if expiration_str == "Lifetime":
                            is_expired = False
                            days_remaining = 36500  # Effectively forever
                        else:
                            try:
                                expiration_date = datetime.datetime.strptime(expiration_str, "%Y-%m-%d").date()
                                is_expired = expiration_date < today
                                days_remaining = (expiration_date - today).days
                            except ValueError:
                                is_expired = False
                                days_remaining = 0
                        
                        if expired == "expired" and not is_expired:
                            continue
                        elif expired == "valid" and is_expired:
                            continue
                        elif expired == "expiring-soon" and (is_expired or days_remaining > 30):
                            continue
                    
                    # Add calculated fields
                    if 'ExpirationDate' in row and row['ExpirationDate'] != "Lifetime":
                        try:
                            expiration_date = datetime.datetime.strptime(row['ExpirationDate'], "%Y-%m-%d").date()
                            row['days_remaining'] = (expiration_date - today).days
                            row['is_expired'] = expiration_date < today
                        except ValueError:
                            row['days_remaining'] = 0
                            row['is_expired'] = False
                    else:
                        row['days_remaining'] = 36500  # Effectively forever
                        row['is_expired'] = False
                    
                    licenses.append(row)
            
            return licenses
        except Exception as e:
            logger.error(f"Error listing licenses: {e}")
            return []
    
    def get_license_details(self, license_id):
        """Get detailed information about a specific license"""
        try:
            with open(LICENSE_DB_PATH, 'r', newline='') as file:
                reader = csv.DictReader(file)
                
                for row in reader:
                    if row.get('LicenseID', '') == license_id:
                        return row
            
            return None
        except Exception as e:
            logger.error(f"Error getting license details: {e}")
            return None
    
    def get_reactivation_details(self, request_id):
        """Get detailed information about a specific reactivation request"""
        try:
            with open(REACTIVATION_DB_PATH, 'r', newline='') as file:
                reader = csv.DictReader(file)
                
                for row in reader:
                    if row.get('id', '') == request_id:
                        return row
            
            return None
        except Exception as e:
            logger.error(f"Error getting reactivation details: {e}")
            return None
    
    def revoke_license(self, license_id, reason):
        """Revoke a license"""
        return self._update_license_status(license_id, f"revoked ({reason})")
    
    def get_dashboard_data(self):
        """Get summary data for the dashboard"""
        try:
            # Default empty data structure
            dashboard_data = {
                "totalLicenses": 0,
                "activeLicenses": 0,
                "expiringLicenses": 0,
                "pendingReactivations": 0,
                "recentLicenses": [],
                "tierDistribution": {}
            }
            
            # Count licenses by status and tier
            today = datetime.datetime.now().date()
            licenses = self.list_licenses()
            tier_counts = {}
            active_count = 0
            expiring_count = 0
            recent_licenses = []
            
            for license in licenses:
                # Count by tier
                tier = license.get('Tier', 'Unknown')
                tier_counts[tier] = tier_counts.get(tier, 0) + 1
                
                # Count active licenses
                if license.get('Status', '') == 'active':
                    active_count += 1
                    
                    # Check if expiring soon (30 days)
                    if license.get('ExpirationDate', '') != 'Lifetime':
                        try:
                            expiration_date = datetime.datetime.strptime(license.get('ExpirationDate', ''), "%Y-%m-%d").date()
                            days_remaining = (expiration_date - today).days
                            if 0 < days_remaining <= 30:
                                expiring_count += 1
                        except ValueError:
                            pass
                
                # Add to recent licenses
                if len(recent_licenses) < 5:
                    recent_licenses.append(license)
            
            # Count pending reactivation requests
            pending_reactivations = len(self.list_reactivation_requests(status='pending'))
            
            # Update the dashboard data
            dashboard_data['totalLicenses'] = len(licenses)
            dashboard_data['activeLicenses'] = active_count
            dashboard_data['expiringLicenses'] = expiring_count
            dashboard_data['pendingReactivations'] = pending_reactivations
            dashboard_data['recentLicenses'] = recent_licenses
            dashboard_data['tierDistribution'] = tier_counts
            
            return dashboard_data
        except Exception as e:
            logger.error(f"Error generating dashboard data: {e}")
            return None
    
    def verify_license(self, license_key):
        """Verify a license key without hardware binding check"""
        try:
            # Clean up the license key (remove dashes and whitespace)
            clean_license = re.sub(r'[\s-]', '', license_key)
            
            # Split the license key into data and signature parts
            parts = clean_license.split('|')
            if len(parts) != 2:
                logger.error("Invalid license key format")
                return None
                
            encoded_data = parts[0]
            encoded_signature = parts[1]
            
            # Decode the data and signature
            license_data = base64.b64decode(encoded_data).decode('utf-8')
            signature = base64.b64decode(encoded_signature)
            
            # Verify the signature
            try:
                self.public_key.verify(
                    signature,
                    license_data.encode(),
                    padding.PSS(
                        mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH
                    ),
                    hashes.SHA256()
                )
                
                # Parse license data
                license_parts = license_data.split('|')
                
                if len(license_parts) < 3:
                    logger.error("Invalid license data format")
                    return None
                
                # New format: license_id|hwid|expiration|features|customer_id
                license_id = license_parts[0]
                hwid = license_parts[1]
                expiration_timestamp = int(license_parts[2])
                features = license_parts[3].split(',') if len(license_parts) > 3 else ["basic"]
                customer_id = license_parts[4] if len(license_parts) > 4 else ""
                
                # Check if license has expired
                current_timestamp = int(datetime.datetime.now().timestamp())
                expired = current_timestamp > expiration_timestamp
                expiration_date = datetime.datetime.fromtimestamp(expiration_timestamp).strftime('%Y-%m-%d')
                
                return {
                    "valid": True,
                    "signature_valid": True,
                    "license_id": license_id,
                    "hardware_id": hwid,
                    "customer_id": customer_id,
                    "features": features,
                    "expired": expired,
                    "expiration_date": "Lifetime" if expiration_timestamp > 4102444800 else expiration_date  # 4102444800 is timestamp for 2100-01-01
                }
                
            except Exception as e:
                logger.error(f"Signature verification failed: {e}")
                return {
                    "valid": False,
                    "signature_valid": False,
                    "message": "Invalid license signature"
                }
                
        except Exception as e:
            logger.error(f"Error verifying license: {e}")
            return None

    def backup_databases(self):
        """Create backups of the license and reactivation databases"""
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Backup license database
            license_backup_path = f"licenses_backup_{timestamp}.csv"
            if LICENSE_DB_PATH.exists():
                with open(LICENSE_DB_PATH, 'r', newline='') as src, open(license_backup_path, 'w', newline='') as dst:
                    dst.write(src.read())
            
            # Backup reactivation database
            reactivation_backup_path = f"reactivation_backup_{timestamp}.csv"
            if REACTIVATION_DB_PATH.exists():
                with open(REACTIVATION_DB_PATH, 'r', newline='') as src, open(reactivation_backup_path, 'w', newline='') as dst:
                    dst.write(src.read())
            
            logger.info(f"Databases backed up: {license_backup_path}, {reactivation_backup_path}")
            return {
                "success": True,
                "license_backup": license_backup_path,
                "reactivation_backup": reactivation_backup_path
            }
        except Exception as e:
            logger.error(f"Error backing up databases: {e}")
            return {"success": False, "message": str(e)}

    def verify_database_integrity(self):
        """Check the integrity of the license and reactivation databases"""
        issues = []
        
        try:
            # Check license database
            if LICENSE_DB_PATH.exists():
                with open(LICENSE_DB_PATH, 'r', newline='') as file:
                    reader = csv.DictReader(file)
                    row_num = 1  # Skip header row
                    for row in reader:
                        row_num += 1
                        # Check required fields
                        for field in ["LicenseID", "CustomerName", "Email", "HardwareID", "LicenseKey"]:
                            if not row.get(field):
                                issues.append(f"License DB row {row_num}: Missing {field}")
                        
                        # Verify LicenseID format
                        try:
                            uuid.UUID(row.get("LicenseID", ""))
                        except ValueError:
                            issues.append(f"License DB row {row_num}: Invalid LicenseID format")
                        
                        # Verify date formats
                        for date_field in ["CreationDate", "ExpirationDate"]:
                            if row.get(date_field) and row.get(date_field) != "Lifetime":
                                try:
                                    datetime.datetime.strptime(row[date_field], "%Y-%m-%d")
                                except ValueError:
                                    issues.append(f"License DB row {row_num}: Invalid {date_field} format")
            
            # Check reactivation database
            if REACTIVATION_DB_PATH.exists():
                with open(REACTIVATION_DB_PATH, 'r', newline='') as file:
                    reader = csv.DictReader(file)
                    row_num = 1  # Skip header row
                    for row in reader:
                        row_num += 1
                        # Check required fields
                        for field in ["id", "license_key", "email"]:
                            if not row.get(field):
                                issues.append(f"Reactivation DB row {row_num}: Missing {field}")
                        
                        # Validate status value
                        if row.get("status") not in ["pending", "approved", "rejected", ""]:
                            issues.append(f"Reactivation DB row {row_num}: Invalid status '{row.get('status')}'")
            
            return {
                "valid": len(issues) == 0,
                "issues": issues
            }
        except Exception as e:
            logger.error(f"Error verifying database integrity: {e}")
            issues.append(f"Error during verification: {str(e)}")
            return {
                "valid": False,
                "issues": issues
            }
    
    def cleanup_expired_licenses(self):
        """Mark all expired licenses as 'expired'"""
        try:
            licenses = []
            today = datetime.datetime.now().date()
            count = 0
            
            with open(LICENSE_DB_PATH, 'r', newline='') as file:
                reader = csv.DictReader(file)
                fieldnames = reader.fieldnames
                
                for row in reader:
                    # Skip lifetime or already expired licenses
                    if row.get('ExpirationDate') == 'Lifetime' or row.get('Status') == 'expired':
                        licenses.append(row)
                        continue
                    try:
                        expiration_date = datetime.datetime.strptime(row.get('ExpirationDate', ''), "%Y-%m-%d").date()
                        
                        # Check if expired
                        if expiration_date < today and row.get('Status') == 'active':
                            row['Status'] = 'expired'
                            count += 1
                    except ValueError:
                        # If date format is invalid, don't change the status
                        pass
                    
                    licenses.append(row)
            
            # Write updated data back to the file
            with open(LICENSE_DB_PATH, 'w', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(licenses)
            
            logger.info(f"Cleaned up {count} expired licenses")
            return {"success": True, "count": count}
        except Exception as e:
            logger.error(f"Error cleaning up expired licenses: {e}")
            return {"success": False, "message": str(e)}

# Create a Flask application
app = Flask(__name__, static_folder='static', template_folder='.')
license_manager = LicenseManager()

# Ensure the static directory exists
os.makedirs('static', exist_ok=True)

# Route for the main admin dashboard
@app.route('/')
def index():
    return render_template('admin.html')

# Route for client page
@app.route('/index.html')
def client_index():
    return render_template('index.html')

# Route for client dashboard
@app.route('/dashboard.html')
def client_dashboard():
    return render_template('dashboard.html')

# Route for serving static files
@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

# Route for serving CSS and JS files directly from root
@app.route('/<path:filename>')
def serve_root_files(filename):
    if filename.endswith('.css') or filename.endswith('.js'):
        return send_from_directory('.', filename)
    return render_template('404.html'), 404

# API route for dashboard data
@app.route('/api/admin/dashboard')
def api_dashboard():
    data = license_manager.get_dashboard_data()
    if data:
        return jsonify(data)
    return jsonify({"error": "Failed to get dashboard data"}), 500

# API route for listing licenses
@app.route('/api/admin/licenses')
def api_licenses():
    status = request.args.get('status', 'all')
    expiration = request.args.get('expiration', 'all')
    tier = request.args.get('tier', 'all')
    search = request.args.get('search', '')
    
    # Convert 'all' to None for filters
    status = None if status == 'all' else status
    tier = None if tier == 'all' else tier
    expiration = None if expiration == 'all' else expiration
    search = None if not search else search
    
    licenses = license_manager.list_licenses(status, expiration, tier, search)
    return jsonify({"licenses": licenses})

# API route for license details
@app.route('/api/admin/license/<license_id>')
def api_license_details(license_id):
    license_details = license_manager.get_license_details(license_id)
    if license_details:
        return jsonify(license_details)
    return jsonify({"error": "License not found"}), 404

# API route for generating a license
@app.route('/api/admin/generate-license', methods=['POST'])
def api_generate_license():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        hwid = data.get('hwid')
        duration = data.get('duration')
        tier = data.get('tier')
        name = data.get('name')
        email = data.get('email')
        notes = data.get('notes', '')
        
        if not hwid or not duration or not tier or not name or not email:
            return jsonify({"error": "Missing required fields"}), 400
        
        license_data = license_manager.generate_license(hwid, duration, tier, name, email, notes)
        if license_data:
            return jsonify(license_data)
        return jsonify({"error": "Failed to generate license"}), 500
    except Exception as e:
        logger.error(f"Error in generate license API: {e}")
        return jsonify({"error": str(e)}), 500

# API route for revoking a license
@app.route('/api/admin/revoke-license', methods=['POST'])
def api_revoke_license():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        license_id = data.get('id')
        reason = data.get('reason')
        
        if not license_id or not reason:
            return jsonify({"error": "Missing required fields"}), 400
        
        result = license_manager.revoke_license(license_id, reason)
        if result:
            return jsonify({"success": True})
        return jsonify({"error": "Failed to revoke license"}), 500
    except Exception as e:
        logger.error(f"Error in revoke license API: {e}")
        return jsonify({"error": str(e)}), 500

# API route for reactivation requests
@app.route('/api/admin/reactivations')
def api_reactivations():
    pending = license_manager.list_reactivation_requests(status='pending')
    approved = license_manager.list_reactivation_requests(status='approved')
    rejected = license_manager.list_reactivation_requests(status='rejected')
    
    return jsonify({
        "pending": pending,
        "approved": approved,
        "rejected": rejected
    })

# API route for reactivation details
@app.route('/api/admin/reactivation/<request_id>')
def api_reactivation_details(request_id):
    details = license_manager.get_reactivation_details(request_id)
    if details:
        return jsonify(details)
    return jsonify({"error": "Reactivation request not found"}), 404

# API route for processing a reactivation request
@app.route('/api/admin/process-reactivation', methods=['POST'])
def api_process_reactivation():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        request_id = data.get('id')
        action = data.get('action')
        
        if not request_id or not action:
            return jsonify({"error": "Missing required fields"}), 400
        
        # Convert action to status
        status = "approved" if action == "approve" else "rejected"
        
        result = license_manager.process_reactivation(request_id, status)
        if result:
            if isinstance(result, dict) and 'license_key' in result:
                return jsonify({
                    "success": True,
                    "license_key": result['license_key'],
                    "formatted_key": result['formatted_key'],
                    "license_id": result['license_id']
                })
            return jsonify({"success": True})
        return jsonify({"error": "Failed to process reactivation request"}), 500
    except Exception as e:
        logger.error(f"Error in process reactivation API: {e}")
        return jsonify({"error": str(e)}), 500

# API route for generating new key pair
@app.route('/api/admin/keygen', methods=['POST'])
def api_keygen():
    result = license_manager._generate_key_pair()
    return jsonify(result)

# API route for downloading public key
@app.route('/api/admin/download-public-key')
def api_download_public_key():
    if PUBLIC_KEY_PATH.exists():
        return send_file(PUBLIC_KEY_PATH, as_attachment=True)
    return jsonify({"error": "Public key not found"}), 404

# API route for backing up private key
@app.route('/api/admin/backup-private-key')
def api_backup_private_key():
    if PRIVATE_KEY_PATH.exists():
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"private_key_backup_{timestamp}.pem"
        with open(PRIVATE_KEY_PATH, 'rb') as src, open(backup_filename, 'wb') as dst:
            dst.write(src.read())
        return send_file(backup_filename, as_attachment=True)
    return jsonify({"error": "Private key not found"}), 404

# API route for backing up databases
@app.route('/api/admin/backup-databases')
def api_backup_databases():
    result = license_manager.backup_databases()
    return jsonify(result)

# API route for verifying database integrity
@app.route('/api/admin/verify-databases')
def api_verify_databases():
    result = license_manager.verify_database_integrity()
    return jsonify(result)

# API route for cleaning up expired licenses
@app.route('/api/admin/cleanup-licenses', methods=['POST'])
def api_cleanup_licenses():
    result = license_manager.cleanup_expired_licenses()
    return jsonify(result)

# API route for exporting licenses to CSV
@app.route('/api/admin/export-licenses')
def api_export_licenses():
    if LICENSE_DB_PATH.exists():
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        export_filename = f"licenses_export_{timestamp}.csv"
        with open(LICENSE_DB_PATH, 'rb') as src, open(export_filename, 'wb') as dst:
            dst.write(src.read())
        return send_file(export_filename, as_attachment=True)
    return jsonify({"error": "License database not found"}), 404

# API route for setting updates
@app.route('/api/admin/settings', methods=['POST'])
def api_settings():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        # Here you could implement settings changes, for demo we just return success
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error in settings API: {e}")
        return jsonify({"error": str(e)}), 500

# API routes for the client application
@app.route('/api/hwid')
def api_hwid():
    # In a real application, this would call your client-side hardware ID function
    # For demo purposes, we'll return a mock hardware ID
    mock_hwid = hashlib.sha256(f"{sys.platform.node()}:{platform.platform()}".encode()).hexdigest()
    return jsonify({"hwid": mock_hwid})

@app.route('/api/verify', methods=['POST'])
def api_verify():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        license_key = data.get('license_key', '')
        
        # Verify the license
        verification_result = license_manager.verify_license(license_key)
        if verification_result:
            # Get hardware ID for response
            mock_hwid = hashlib.sha256(f"{platform.node()}:{platform.platform()}".encode()).hexdigest()
            verification_result["hwid"] = mock_hwid
            
            return jsonify(verification_result)
        return jsonify({"valid": False, "message": "Failed to verify license"}), 500
    except Exception as e:
        logger.error(f"Error in verify API: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/request-reactivation', methods=['POST'])
def api_request_reactivation():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        license_key = data.get('license_key', '')
        email = data.get('email', '')
        reason = data.get('reason', '')
        old_hwid = data.get('old_hwid', '')
        new_hwid = data.get('new_hwid', '')
        
        if not license_key or not email or not reason or not new_hwid:
            return jsonify({"error": "Missing required fields"}), 400
        
        # Store the reactivation request
        try:
            # Generate unique ID for the request
            request_id = str(uuid.uuid4())[:8]
            
            # Prepare the request data
            reactivation_request = {
                "id": request_id,
                "license_key": license_key,
                "email": email,
                "old_hwid": old_hwid,
                "new_hwid": new_hwid,
                "reason": reason,
                "timestamp": datetime.datetime.now().isoformat(),
                "status": "pending"
            }
            
            # Check if reactivation database exists
            file_exists = os.path.isfile(REACTIVATION_DB_PATH)
            
            # Write to the CSV file
            with open(REACTIVATION_DB_PATH, 'a', newline='') as file:
                fieldnames = ["id", "license_key", "email", "old_hwid", "new_hwid", 
                             "timestamp", "reason", "status", "processed_date", "new_license_id"]
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                
                if not file_exists:
                    writer.writeheader()
                    
                writer.writerow(reactivation_request)
            
            return jsonify({
                "success": True, 
                "message": "Reactivation request submitted successfully. Our support team will contact you."
            })
            
        except Exception as e:
            logger.error(f"Error storing reactivation request: {e}")
            return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"Error in reactivation request API: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/check-activation-status', methods=['POST'])
def api_check_activation_status():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        license_key = data.get('license_key', '')
        email = data.get('email', '')
        
        if not license_key or not email:
            return jsonify({"error": "License key and email are required"}), 400
        
        # Check for the reactivation status
        status = "not_found"
        message = "No reactivation request found for this license key and email."
        
        if os.path.isfile(REACTIVATION_DB_PATH):
            with open(REACTIVATION_DB_PATH, 'r', newline='') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    # Clean up the license key for comparison
                    stored_key = re.sub(r'[\s-]', '', row.get('license_key', ''))
                    input_key = re.sub(r'[\s-]', '', license_key)
                    
                    if (stored_key == input_key and 
                        row.get('email', '').lower() == email.lower()):
                        status = row.get('status', 'pending')
                        message = get_status_message(status)
                        break
        
        return jsonify({
            "license_key": license_key,
            "email": email,
            "status": status,
            "message": message
        })
        
    except Exception as e:
        logger.error(f"Error checking activation status: {e}")
        return jsonify({"error": str(e)}), 500

def get_status_message(status):
    """
    Get a user-friendly message based on the status
    """
    messages = {
        "pending": "Your reactivation request is being processed. Please check back later.",
        "approved": "Your reactivation request has been approved. Your license is now activated for this hardware.",
        "rejected": "Your reactivation request has been rejected. Please contact support for more information.",
        "completed": "Your license has been reactivated successfully.",
        "not_found": "No reactivation request found for this license key and email."
    }
    return messages.get(status, f"Unknown status: {status}")

@app.route('/api/system-info')
def api_system_info():
    """
    Get detailed system information for diagnostic purposes
    """
    try:
        # In a real application, this would call your hardware components function
        # For demo purposes, we'll return mock data
        component_types = [
            "system", "machine", "architecture", "cpu_id", "board_serial",
            "bios_serial", "disk_serial", "mac_address", "system_uuid"
        ]
        
        # Generate masked components for display
        masked_components = {}
        for key in component_types:
            if key == "system":
                masked_components[key] = platform.system()
            elif key == "machine":
                masked_components[key] = platform.machine()
            elif key == "architecture":
                masked_components[key] = platform.architecture()[0]
            else:
                # Generate a random hash for other components
                value = hashlib.md5(f"{key}:{platform.node()}".encode()).hexdigest()
                masked_components[key] = value[:4] + "****" + value[-4:]
        
        # Get all fingerprint types
        fingerprint_types = ["primary", "secondary", "tertiary", "full", "legacy"]
        fingerprint_types.extend(component_types)
        
        # Generate primary HWID
        primary_hwid = hashlib.sha256(f"{platform.node()}:{platform.platform()}".encode()).hexdigest()
        
        return jsonify({
            "system": sys.platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "architecture": platform.architecture()[0],
            "python_version": platform.python_version(),
            "component_types": component_types,
            "masked_components": masked_components,
            "fingerprint_types": fingerprint_types,
            "primary_hwid": primary_hwid
        })
    except Exception as e:
        logger.error(f"Error getting system info: {e}")
        return jsonify({"error": str(e)}), 500

def main():
    parser = argparse.ArgumentParser(description='License Key Manager for Administrators')
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Generate license command
    generate_parser = subparsers.add_parser('generate', help='Generate a new license key')
    generate_parser.add_argument('--hwid', required=True, help='Hardware ID to bind the license to')
    generate_parser.add_argument('--duration', required=True, choices=LICENSE_DURATIONS.keys(), 
                               help='License duration (15d, 1m, 3m, 6m, 1y, lifetime)')
    generate_parser.add_argument('--tier', required=True, choices=LICENSE_TIERS.keys(),
                               help='License tier (basic, premium, professional, enterprise)')
    generate_parser.add_argument('--name', required=True, help='Customer name')
    generate_parser.add_argument('--email', required=True, help='Customer email')
    generate_parser.add_argument('--notes', default='', help='Additional notes about this license')
    
    # Verify license command
    verify_parser = subparsers.add_parser('verify', help='Verify a license key')
    verify_parser.add_argument('--key', required=True, help='License key to verify')
    
    # List licenses command
    list_parser = subparsers.add_parser('list', help='List licenses')
    list_parser.add_argument('--status', choices=['active', 'revoked', 'reactivated'], 
                           help='Filter by license status')
    list_parser.add_argument('--expired', action='store_true', help='Show only expired licenses')
    list_parser.add_argument('--valid', action='store_true', help='Show only valid (non-expired) licenses')
    
    # Revoke license command
    revoke_parser = subparsers.add_parser('revoke', help='Revoke a license')
    revoke_parser.add_argument('--id', required=True, help='License ID to revoke')
    revoke_parser.add_argument('--reason', required=True, help='Reason for revocation')
    
    # List reactivation requests command
    reactivation_list_parser = subparsers.add_parser('reactivation-list', help='List reactivation requests')
    reactivation_list_parser.add_argument('--status', choices=['pending', 'approved', 'rejected'], 
                                        help='Filter by request status')
    
    # Process reactivation request command
    reactivation_parser = subparsers.add_parser('reactivation', help='Process a reactivation request')
    reactivation_parser.add_argument('--id', required=True, help='Reactivation request ID')
    reactivation_parser.add_argument('--action', required=True, choices=['approve', 'reject'], 
                                   help='Action to take on the request')
    
    # Generate new key pair command
    keygen_parser = subparsers.add_parser('keygen', help='Generate a new RSA key pair')
    
    # Web server command
    server_parser = subparsers.add_parser('server', help='Start the web server')
    server_parser.add_argument('--port', type=int, default=5000, help='Port to run the server on (default: 5000)')
    server_parser.add_argument('--host', default='0.0.0.0', help='Host to run the server on (default: 0.0.0.0)')
    server_parser.add_argument('--debug', action='store_true', help='Run the server in debug mode')
    
    args = parser.parse_args()
    
    if args.command == 'server':
        # Start the web server
        app.run(host=args.host, port=args.port, debug=args.debug)
        return
    
    # For other commands, use the CLI interface
    license_manager = LicenseManager()
    
    if args.command == 'generate':
        license_data = license_manager.generate_license(
            args.hwid, args.duration, args.tier,
            args.name, args.email, args.notes
        )
        
        if license_data:
            print("\n=== License Generated Successfully ===")
            print(f"License ID: {license_data['license_id']}")
            print(f"Customer ID: {license_data['customer_id']}")
            print(f"Tier: {license_data['tier']}")
            print(f"Features: {', '.join(license_data['features'])}")
            print(f"Valid until: {license_data['expiration_date']}")
            print("\nLicense Key (for copy/paste):")
            print(license_data['license_key'])
            print("\nFormatted License Key (for display):")
            print(license_data['formatted_key'])
        else:
            print("Failed to generate license. Check the log for details.")
    
    elif args.command == 'verify':
        result = license_manager.verify_license(args.key)
        
        if result:
            if result.get('valid', False):
                print("\n=== License Verification Results ===")
                print(f"Status: {'EXPIRED' if result.get('expired', False) else 'VALID'}")
                print(f"License ID: {result.get('license_id', 'N/A')}")
                print(f"Customer ID: {result.get('customer_id', 'N/A')}")
                print(f"Hardware ID: {result.get('hardware_id', 'N/A')}")
                print(f"Features: {', '.join(result.get('features', []))}")
                print(f"Expiration Date: {result.get('expiration_date', 'N/A')}")
            else:
                print(f"Invalid license: {result.get('message', 'Unknown error')}")
        else:
            print("License verification failed. Check the log for details.")
    
    elif args.command == 'list':
        expired_filter = None
        if args.expired:
            expired_filter = "expired"
        elif args.valid:
            expired_filter = "valid"
        
        licenses = license_manager.list_licenses(args.status, expired_filter)
        
        if licenses:
            print(f"\n=== Licenses ({len(licenses)}) ===")
            print(f"{'ID':<36} | {'Customer':<20} | {'Email':<25} | {'Expiration':<12} | {'Status':<15} | {'Tier':<15}")
            print("-" * 130)
            
            for license in licenses:
                print(f"{license.get('LicenseID', 'N/A'):<36} | {license.get('CustomerName', 'N/A'):<20} | "
                      f"{license.get('Email', 'N/A'):<25} | {license.get('ExpirationDate', 'N/A'):<12} | "
                      f"{license.get('Status', 'N/A'):<15} | {license.get('Tier', 'N/A'):<15}")
        else:
            print("No licenses found matching the criteria.")
    
    elif args.command == 'revoke':
        success = license_manager.revoke_license(args.id, args.reason)
        
        if success:
            print(f"License {args.id} has been revoked. Reason: {args.reason}")
        else:
            print(f"Failed to revoke license {args.id}. Check the log for details.")
    
    elif args.command == 'reactivation-list':
        requests = license_manager.list_reactivation_requests(args.status)
        
        if requests:
            print(f"\n=== Reactivation Requests ({len(requests)}) ===")
            print(f"{'ID':<8} | {'License Key (truncated)':<20} | {'Email':<25} | {'Status':<10} | {'Date':<12}")
            print("-" * 85)
            
            for req in requests:
                # Truncate license key for display
                key = req.get('license_key', 'N/A')
                if len(key) > 20:
                    key = key[:17] + "..."
                
                print(f"{req.get('id', 'N/A'):<8} | {key:<20} | "
                      f"{req.get('email', 'N/A'):<25} | {req.get('status', 'N/A'):<10} | "
                      f"{req.get('timestamp', 'N/A')[:10] if 'timestamp' in req else 'N/A':<12}")
        else:
            print("No reactivation requests found matching the criteria.")
    
    elif args.command == 'reactivation':
        action = "approved" if args.action == "approve" else "rejected"
        result = license_manager.process_reactivation(args.id, action)
        
        if result:
            print(f"Reactivation request {args.id} has been {action}.")
            
            if isinstance(result, dict) and action == "approved":
                print("\n=== New License Generated ===")
                print(f"License ID: {result['license_id']}")
                print(f"Valid until: {result['expiration_date']}")
                print("\nLicense Key (for copy/paste):")
                print(result['license_key'])
                print("\nFormatted License Key (for display):")
                print(result['formatted_key'])
        else:
            print(f"Failed to process reactivation request {args.id}. Check the log for details.")
    
    elif args.command == 'keygen':
        result = license_manager._generate_key_pair()
        if result.get('success', False):
            print("New RSA key pair generated successfully.")
            print(f"Private key saved to: {PRIVATE_KEY_PATH}")
            print(f"Public key saved to: {PUBLIC_KEY_PATH}")
            print("\nIMPORTANT: Distribute the public key to your clients and keep the private key secure!")
        else:
            print(f"Failed to generate key pair: {result.get('message', 'Unknown error')}")
    
    else:
        parser.print_help()

# Run self-tests on startup if enabled
if __name__ == '__main__':
    # Check if any arguments were provided
    if len(sys.argv) > 1:
        # If arguments were provided, process them with argparse
        main()
    else:
        # No arguments provided, run in web server mode automatically
        
        # Run self-tests if not disabled
        print("Running self-tests...")
        license_manager = LicenseManager()
        # You may want to implement a run_self_tests() function or use an existing one
        
        # Enable debug output to see error messages
        print("Starting web server on http://127.0.0.1:5002")
        app.run(debug=True, port=5002, host='127.0.0.1')
                    
                    