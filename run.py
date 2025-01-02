#!/usr/bin/env python3

import os
import sys
import json
import shutil
import logging
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, Any
import multiprocessing
import psutil

@dataclass
class SystemCapabilities:
    cpu_cores: int
    available_memory_mb: int
    is_slow_storage: bool
    use_parallel: bool
    compression_threads: int

@dataclass
class BorgConfig:
    base_dir: str = "/config/borg"
    cache_dir: str = "/config/borg/cache"
    backup_dir: str = "/backup/borg_unpacked"
    ssh_known_hosts: str = "/config/borg/known_hosts"
    ssh_key: str = "/config/borg/keys/borg_backup"
    
    # These will be loaded from Home Assistant config
    passphrase: Optional[str] = None
    repo_url: Optional[str] = None
    user: Optional[str] = None
    host: Optional[str] = None
    reponame: Optional[str] = None
    compression: str = "zstd"
    debug: bool = False
    keep_snapshots: int = 5
    ssh_params: str = ""

class BorgBackup:
    def __init__(self):
        self.logger = self._setup_logging()
        self.config = self._load_config()
        self.capabilities = self._detect_system_capabilities()
        self._setup_environment()

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("borg_backup")
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def _detect_system_capabilities(self) -> SystemCapabilities:
        cpu_cores = multiprocessing.cpu_count()
        available_memory = psutil.virtual_memory().available // (1024 * 1024)  # Convert to MB
        
        # Check for slow storage
        root_device = Path("/").resolve()
        is_slow_storage = False
        
        try:
            if "mmcblk" in str(root_device) or self._is_rotational_disk(str(root_device)):
                is_slow_storage = True
        except Exception:
            self.logger.warning("Could not determine storage type, assuming slow storage")
            is_slow_storage = True

        use_parallel = (cpu_cores > 1 and 
                       available_memory > 1024 and 
                       not is_slow_storage)
        
        compression_threads = (cpu_cores - 1) if use_parallel else 1

        return SystemCapabilities(
            cpu_cores=cpu_cores,
            available_memory_mb=available_memory,
            is_slow_storage=is_slow_storage,
            use_parallel=use_parallel,
            compression_threads=compression_threads
        )

    def _is_rotational_disk(self, device_path: str) -> bool:
        try:
            device = os.path.realpath(device_path)
            sys_path = f"/sys/block/{device.split('/')[-1]}/queue/rotational"
            with open(sys_path, 'r') as f:
                return f.read().strip() == "1"
        except Exception:
            return True

    def _load_config(self) -> BorgConfig:
        try:
            result = subprocess.run(
                ['ha', 'config', '--raw-json'], 
                capture_output=True, 
                text=True,
                check=True
            )
            options = json.loads(result.stdout)['data']['options']
            
            config = BorgConfig()
            config.passphrase = options.get('borg_passphrase')
            config.repo_url = options.get('borg_repo_url')
            config.user = options.get('borg_user')
            config.host = options.get('borg_host')
            config.reponame = options.get('borg_reponame')
            config.compression = options.get('borg_compression', 'zstd')
            config.debug = options.get('borg_backup_debug', False)
            config.keep_snapshots = int(options.get('borg_backup_keep_snapshots', 5))
            config.ssh_params = options.get('borg_ssh_params', '')
            
            self._validate_config(config)
            return config
            
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to get config from Home Assistant: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse config JSON: {e}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"Unexpected error loading config: {e}")
            sys.exit(1)

    def _validate_config(self, config: BorgConfig):
        if not config.repo_url and not config.host:
            raise ValueError("Either 'borg_repo_url' or 'borg_host' must be defined")
        if config.repo_url and config.host:
            raise ValueError("Cannot define both 'borg_repo_url' and 'borg_host'")
        if config.host and not config.reponame:
            raise ValueError("When using borg_host, borg_reponame must be defined")

    def _setup_environment(self):
        """Setup environment variables for Borg including encryption settings."""
        os.environ['BORG_BASE_DIR'] = self.config.base_dir
        os.environ['BORG_CACHE_DIR'] = self.config.cache_dir
        
        # Handle encryption settings
        if self.config.passphrase:
            os.environ['BORG_PASSPHRASE'] = self.config.passphrase
            # Remove any previous unencrypted access setting
            os.environ.pop('BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK', None)
        else:
            self.logger.warning("No passphrase set - repository will be initialized without encryption!")
            os.environ['BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK'] = 'yes'
            os.environ.pop('BORG_PASSPHRASE', None)

        # Set up SSH configuration with additional parameters
        ssh_cmd = f"ssh -o UserKnownHostsFile={self.config.ssh_known_hosts} -i {self.config.ssh_key}"
        if self.config.ssh_params:
            ssh_cmd = f"{ssh_cmd} {self.config.ssh_params}"
        os.environ['BORG_RSH'] = ssh_cmd

        # Create required directories
        Path(self.config.base_dir).mkdir(parents=True, exist_ok=True)
        Path(self.config.cache_dir).mkdir(parents=True, exist_ok=True)
        Path(self.config.backup_dir).mkdir(parents=True, exist_ok=True)

    def unpack_backup(self, snap_slug: str):
        target_dir = Path(self.config.backup_dir) / snap_slug
        target_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"Unpacking backup {snap_slug}")
        
        tar_cmd = ['tar']
        if self.capabilities.use_parallel and shutil.which('pigz'):
            self.logger.info(f"Using parallel decompression with {self.capabilities.compression_threads} threads")
            tar_cmd.extend(['--use-compress-program', f'pigz -p {self.capabilities.compression_threads}'])
        
        tar_cmd.extend(['-xf', f'/backup/{snap_slug}.tar', '-C', str(target_dir)])
        
        try:
            subprocess.run(tar_cmd, check=True)
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to unpack backup: {e}")
            raise

        # Handle nested archives
        for targz in target_dir.rglob('*.tar.gz'):
            extract_dir = targz.with_suffix('').with_suffix('')
            extract_dir.mkdir(parents=True, exist_ok=True)
            
            try:
                self._extract_nested_archive(targz, extract_dir)
                targz.unlink()
            except Exception as e:
                self.logger.error(f"Failed to extract nested archive {targz}: {e}")
                raise

    def _extract_nested_archive(self, archive_path: Path, extract_dir: Path):
        tar_cmd = ['tar']
        if self.capabilities.use_parallel and shutil.which('pigz'):
            tar_cmd.extend(['--use-compress-program', f'pigz -p {self.capabilities.compression_threads}'])
        tar_cmd.extend(['-xf', str(archive_path), '-C', str(extract_dir)])
        
        subprocess.run(tar_cmd, check=True)

    def init_borg_repo(self):
        """Initialize Borg repository with encryption if it doesn't exist."""
        config_path = Path(self.config.base_dir) / ".config/borg/security"
        
        if not config_path.exists():
            self.logger.info("Initializing backup repository with encryption")
            cmd = [
                'borg', 'init',
                '--encryption=repokey-blake2'
            ]
            
            if self.config.debug:
                cmd.append('--debug')
                
            try:
                subprocess.run(cmd, check=True, env=os.environ)
                self.logger.info("Repository initialized successfully with encryption")
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Failed to initialize repository: {e}")
                raise

    def create_backup(self):
        """Create a new backup with encryption."""
        try:
            # Ensure repository is initialized with encryption
            self.init_borg_repo()
            
            backup_time = subprocess.check_output(['date', '+%Y-%m-%d-%H:%M']).decode().strip()
            
            self.logger.info("Creating Home Assistant backup")
            result = self._create_ha_backup(backup_time)
            
            if result:
                snap_slug = result['slug']
                self.unpack_backup(snap_slug)
                
                self.logger.info("Creating encrypted Borg backup")
                self._create_borg_backup(backup_time, snap_slug)
                
                self._cleanup_old_backups()
        except Exception as e:
            self.logger.error(f"Backup creation failed: {e}")
            sys.exit(1)
        finally:
            self._cleanup_temp_files()

    def _create_ha_backup(self, backup_time: str) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                ['ha', 'backup', 'new', '--name', f"borg-{backup_time}", '--raw-json'],
                capture_output=True,
                text=True,
                check=True
            )
            data = json.loads(result.stdout)
            
            if data['result'] != 'ok':
                raise RuntimeError("Failed to create Home Assistant backup")
                
            return data['data']
            
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to create Home Assistant backup: {e}")
            raise
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse backup creation response: {e}")
            raise

    def _create_borg_backup(self, backup_time: str, snap_slug: str):
        cmd = [
            'borg', 'create',
            '--compression', f"{self.config.compression},9",
            '--stats',
            '--exclude', '*.pyc',
            '--exclude', '__pycache__',
            '--exclude', '*.tmp',
            '--exclude', '*.log',
            f"::{backup_time}",
            f"{self.config.backup_dir}/{snap_slug}"
        ]
        
        if self.config.debug:
            cmd.insert(1, '--debug')
            
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Borg backup creation failed: {e}")
            raise

    def _cleanup_old_backups(self):
        try:
            # Reload backup list
            subprocess.run(['ha', 'backup', 'reload'], check=True)
            
            # Get list of backups
            result = subprocess.run(
                ['ha', 'backup', '--raw-json'],
                capture_output=True,
                text=True,
                check=True
            )
            
            data = json.loads(result.stdout)
            backups = data['data']['backups']
            
            # Sort backups by date and get ones to remove
            backups.sort(key=lambda x: x['date'])
            to_remove = backups[:-self.config.keep_snapshots] if len(backups) > self.config.keep_snapshots else []
            
            # Remove old backups
            for backup in to_remove:
                self.logger.info(f"Removing backup {backup['name']} ({backup['slug']})")
                subprocess.run(['ha', 'backup', 'remove', backup['slug']], check=True)
                
        except Exception as e:
            self.logger.error(f"Failed to cleanup old backups: {e}")
            raise

    def _cleanup_temp_files(self):
        try:
            if Path(self.config.backup_dir).exists():
                shutil.rmtree(self.config.backup_dir)
        except Exception as e:
            self.logger.error(f"Failed to cleanup temporary files: {e}")

def main():
    backup = BorgBackup()
    backup.create_backup()

if __name__ == "__main__":
    main()
