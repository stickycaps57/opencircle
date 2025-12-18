"""
FTP utilities for file upload and management with InfinityFree
"""
import ftplib
import os
import io
from typing import Optional, Tuple
from fastapi import UploadFile
import uuid
from pathlib import Path

class FTPManager:
    """FTP file manager for InfinityFree hosting"""

    def __init__(self):
        self.host = os.getenv("FTP_HOST")
        self.username = os.getenv("FTP_USERNAME") 
        self.password = os.getenv("FTP_PASSWORD")
        self.port = int(os.getenv("FTP_PORT", "21"))
        self.base_path = os.getenv("FTP_BASE_PATH", "/htdocs/uploads")  # InfinityFree public folder
        self.base_url = os.getenv(
            "FTP_BASE_URL", "https://opencircle-mysql.infinityfree.me/uploads"
        )

    def _connect(self) -> ftplib.FTP:
        """Create FTP connection"""
        if not all([self.host, self.username, self.password]):
            raise ValueError("FTP credentials not configured. Set FTP_HOST, FTP_USERNAME, FTP_PASSWORD environment variables.")

        ftp = ftplib.FTP()
        ftp.connect(self.host, self.port)
        ftp.login(self.username, self.password)
        return ftp

    def _ensure_directory(self, ftp: ftplib.FTP, directory: str) -> None:
        """Create directory if it doesn't exist"""
        try:
            ftp.cwd(directory)
        except ftplib.error_perm:
            # Directory doesn't exist, create it
            parts = directory.strip('/').split('/')
            current_path = ''

            for part in parts:
                if part:
                    current_path += f'/{part}'
                    try:
                        ftp.mkd(current_path)
                    except ftplib.error_perm:
                        # Directory might already exist
                        pass
            ftp.cwd(directory)

    def upload_file(self, file: UploadFile, uploader_uuid: str) -> Tuple[str, str, str]:
        """
        Upload file to FTP server
        
        Args:
            file: FastAPI UploadFile object
            uploader_uuid: UUID of the user uploading the file
            
        Returns:
            Tuple[str, str, str]: (directory, filename, public_url)
        """
        try:
            # Generate unique filename
            file_extension = Path(file.filename).suffix
            unique_filename = f"{uuid.uuid4().hex}{file_extension}"

            # Create directory structure: /uploads/uploader_uuid/
            directory = f"{uploader_uuid}"
            ftp_directory = f"{self.base_path}/{directory}"

            # Connect and upload
            ftp = self._connect()

            # Ensure directory exists
            self._ensure_directory(ftp, ftp_directory)

            # Upload file
            file.file.seek(0)  # Reset file pointer
            ftp.storbinary(f'STOR {unique_filename}', file.file)
            ftp.quit()

            # Generate public URL
            public_url = f"{self.base_url}/{directory}/{unique_filename}"

            return directory, unique_filename, public_url

        except Exception as e:
            raise Exception(f"Failed to upload file to FTP: {str(e)}")

    def delete_file(self, directory: str, filename: str) -> bool:
        """
        Delete file from FTP server
        
        Args:
            directory: Directory path
            filename: Filename to delete
            
        Returns:
            bool: True if successful
        """
        try:
            ftp = self._connect()
            ftp_path = f"{self.base_path}/{directory}/{filename}"
            ftp.delete(ftp_path)
            ftp.quit()
            return True
        except Exception as e:
            print(f"Failed to delete file from FTP: {str(e)}")
            return False

    def file_exists(self, directory: str, filename: str) -> bool:
        """
        Check if file exists on FTP server
        
        Args:
            directory: Directory path
            filename: Filename to check
            
        Returns:
            bool: True if file exists
        """
        try:
            ftp = self._connect()
            ftp_path = f"{self.base_path}/{directory}"
            ftp.cwd(ftp_path)
            file_list = ftp.nlst()
            ftp.quit()
            return filename in file_list
        except Exception:
            return False

    def get_file_url(self, directory: str, filename: str) -> str:
        """
        Get public URL for a file
        
        Args:
            directory: Directory path
            filename: Filename
            
        Returns:
            str: Public URL to the file
        """
        return f"{self.base_url}/{directory}/{filename}"

    def download_file(self, directory: str, filename: str) -> Optional[bytes]:
        """
        Download file content from FTP server
        
        Args:
            directory: Directory path
            filename: Filename
            
        Returns:
            Optional[bytes]: File content or None if failed
        """
        try:
            ftp = self._connect()
            ftp_path = f"{self.base_path}/{directory}"
            ftp.cwd(ftp_path)

            # Download to memory
            file_data = io.BytesIO()
            ftp.retrbinary(f'RETR {filename}', file_data.write)
            ftp.quit()

            file_data.seek(0)
            return file_data.read()
        except Exception as e:
            print(f"Failed to download file from FTP: {str(e)}")
            return None

# Global FTP manager instance
ftp_manager = FTPManager()
