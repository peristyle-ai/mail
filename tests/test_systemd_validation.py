#!/usr/bin/env python3
"""
Systemd service file validation for mail server.

This script validates the syntax and configuration of systemd service files
without actually starting or stopping any services. Safe to run anytime.
"""

import os
import sys
import re
import subprocess
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ServiceValidator:
    """Validates systemd service file syntax and configuration."""
    
    def __init__(self):
        # Detect project root from script location
        script_dir = Path(__file__).parent.parent
        self.project_root = script_dir
        self.errors = []
        self.warnings = []
    
    def validate_service_file(self, service_path, service_type="user"):
        """
        Validate a single service file.
        
        Args:
            service_path: Path to the .service file
            service_type: "user" or "system"
            
        Returns:
            bool: True if valid, False otherwise
        """
        print(f"\n{'='*60}")
        print(f"Validating {service_type}-level service: {service_path}")
        print('='*60)
        
        if not os.path.exists(service_path):
            self.errors.append(f"Service file not found: {service_path}")
            return False
        
        with open(service_path, 'r') as f:
            content = f.read()
        
        valid = True
        
        # Check for required sections
        if '[Unit]' not in content:
            self.errors.append(f"[{service_type}] Missing [Unit] section")
            valid = False
        
        if '[Service]' not in content:
            self.errors.append(f"[{service_type}] Missing [Service] section")
            valid = False
        
        if '[Install]' not in content:
            self.errors.append(f"[{service_type}] Missing [Install] section")
            valid = False
        
        # Check for required directives in [Service]
        service_section = re.search(r'\[Service\](.*?)(?=\[|\Z)', content, re.DOTALL)
        if service_section:
            service_content = service_section.group(1)
            
            # Check ExecStart
            if 'ExecStart=' not in service_content:
                self.errors.append(f"[{service_type}] Missing ExecStart directive")
                valid = False
            else:
                # Validate the executable path
                exec_match = re.search(r'ExecStart=(.+)', service_content)
                if exec_match:
                    exec_path = exec_match.group(1).split()[0]
                    # Expand systemd specifiers like %h (home directory)
                    exec_path_expanded = exec_path.replace('%h', str(Path.home()))
                    
                    if not os.path.exists(exec_path_expanded):
                        self.errors.append(f"[{service_type}] ExecStart path does not exist: {exec_path} (expanded: {exec_path_expanded})")
                        valid = False
                    elif not os.access(exec_path_expanded, os.X_OK):
                        self.warnings.append(f"[{service_type}] ExecStart path may not be executable: {exec_path}")
            
            # Check Type
            if 'Type=simple' not in service_content and 'Type=' not in service_content:
                self.warnings.append(f"[{service_type}] Service Type not specified (defaults to simple)")
            
            # Check Restart
            if 'Restart=' not in service_content:
                self.warnings.append(f"[{service_type}] No Restart policy specified")
        
        # Check [Unit] section
        unit_section = re.search(r'\[Unit\](.*?)(?=\[|\Z)', content, re.DOTALL)
        if unit_section:
            unit_content = unit_section.group(1)
            
            if 'Description=' not in unit_content:
                self.warnings.append(f"[{service_type}] No Description in [Unit]")
            
            if 'After=' not in unit_content:
                self.warnings.append(f"[{service_type}] No After= dependency specified")
        
        # Check [Install] section
        install_section = re.search(r'\[Install\](.*?)(?=\[|\Z)', content, re.DOTALL)
        if install_section:
            install_content = install_section.group(1)
            
            if 'WantedBy=' not in install_content:
                self.errors.append(f"[{service_type}] Missing WantedBy= in [Install]")
                valid = False
        
        # Try systemd-analyze verify if available (doesn't require sudo for validation)
        try:
            result = subprocess.run(
                ['systemd-analyze', 'verify', service_path],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0 and result.stderr:
                # Filter out warnings about user service
                errors = [line for line in result.stderr.split('\n') 
                         if line and 'Warning' not in line and 'hint' not in line.lower()]
                if errors:
                    self.errors.extend([f"[{service_type}] {e}" for e in errors])
                    valid = False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # systemd-analyze not available, skip this check
            print(f"  Note: systemd-analyze not available, skipping deep validation")
        
        if valid:
            print(f"  ✓ {service_type}-level service file is valid")
        else:
            print(f"  ✗ {service_type}-level service file has errors")
        
        return valid
    
    def validate_install_script(self, script_path, install_type="user"):
        """Validate installation script."""
        print(f"\n{'='*60}")
        print(f"Validating {install_type} install script: {script_path}")
        print('='*60)
        
        if not os.path.exists(script_path):
            self.errors.append(f"Install script not found: {script_path}")
            return False
        
        with open(script_path, 'r') as f:
            content = f.read()
        
        valid = True
        
        # Check for critical commands
        if 'daemon-reload' not in content:
            self.errors.append(f"[{install_type}] Missing 'daemon-reload' in install script")
            valid = False
        
        if 'enable' not in content:
            self.warnings.append(f"[{install_type}] Install script doesn't enable service")
        
        # Check target directory
        if install_type == "user":
            if '.config/systemd/user' not in content:
                self.errors.append("[user] Install script doesn't target user directory")
                valid = False
        else:
            if '/etc/systemd/system' not in content and 'systemctl' in content:
                # Check if it uses sudo
                if 'EUID' in content or 'sudo' in content.lower():
                    pass  # Good, checks for root
                else:
                    self.warnings.append("[system] Install script may not check for root access")
        
        # Check for Python/pip in requirements
        if 'venv' in content or 'virtualenv' in content:
            print(f"  ✓ Install script handles virtual environment")
        
        if valid:
            print(f"  ✓ {install_type} install script is valid")
        else:
            print(f"  ✗ {install_type} install script has errors")
        
        return valid
    
    def validate_all(self):
        """Run all validations."""
        print("\n" + "="*70)
        print("Systemd Service Validation")
        print("="*70)
        
        # Validate user-level service
        user_service = self.project_root / 'systemd' / 'user' / 'mail-server.service'
        user_valid = self.validate_service_file(user_service, "user")
        
        # Validate system-level service
        system_service = self.project_root / 'systemd' / 'mail-server.service'
        system_valid = self.validate_service_file(system_service, "system")
        
        # Validate install scripts
        user_install = self.project_root / 'systemd' / 'user' / 'install.sh'
        user_install_valid = self.validate_install_script(user_install, "user")
        
        system_install = self.project_root / 'systemd' / 'install.sh'
        system_install_valid = self.validate_install_script(system_install, "system")
        
        # Print summary
        print("\n" + "="*70)
        print("Validation Summary")
        print("="*70)
        
        all_valid = user_valid and system_valid and user_install_valid and system_install_valid
        
        if self.errors:
            print("\n✗ Errors Found:")
            for error in self.errors:
                print(f"  - {error}")
        
        if self.warnings:
            print("\n⚠ Warnings:")
            for warning in self.warnings:
                print(f"  - {warning}")
        
        if all_valid and not self.errors:
            print("\n✓ All systemd configurations are valid!")
            print(f"  - User service: {user_service}")
            print(f"  - System service: {system_service}")
            print(f"\nTo install:")
            print(f"  User:  bash {user_install}")
            print(f"  System: sudo bash {system_install}")
            return True
        else:
            print("\n✗ Validation failed with errors")
            return False


def test_systemd_service_validation():
    """
    Pytest test: Validate all systemd service configurations.
    
    This test validates both user-level and system-level systemd service
    files without actually starting or stopping any services. It checks:
    - Service file syntax
    - Required sections and directives
    - Executable paths
    - Install script validity
    """
    validator = ServiceValidator()
    success = validator.validate_all()
    
    # Assert for pytest
    assert success, f"Systemd validation failed with errors: {validator.errors}"


def main():
    """Main entry point for standalone execution."""
    validator = ServiceValidator()
    success = validator.validate_all()
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
