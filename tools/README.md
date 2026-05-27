# Developer Tools

This folder contains diagnostic and inspection utilities used during development and debugging.
These are **not required** for normal use — see the main [README](../README.md) for the standard workflow.

---

## Scripts

| Script | What it does |
|---|---|
| `check_images.py` | Verifies that exported image files are valid and readable |
| `inspect_db.py` | Dumps sample voice messages from `message_message_0.db` |
| `inspect_files.py` | Lists file attachment messages and their metadata |
| `inspect_resource_data.py` | Shows raw content of resource table rows |
| `inspect_resource_detail.py` | Detailed inspection of a specific resource entry |
| `inspect_resource_info_packed.py` | Decodes packed_info fields from resource tables |
| `inspect_resource_md5.py` | Scans resource tables for MD5 hashes |
| `inspect_resource_types.py` | Lists all distinct message types present in resource tables |
| `inspect_resources.py` | General overview of all resource table entries |
| `inspect_specific_file_msg.py` | Deep-inspect a single file message row |
| `inspect_video_file.py` | Checks video file paths and sizes |
| `inspect_videos.py` | Lists video messages across all conversation tables |
| `inspect_voice.py` | Inspects raw SILK voice data in the database |
| `list_attach.py` | Lists all file attachment paths referenced in messages |
| `list_db_storage.py` | Walks and lists the WeChat `db_storage` directory tree |
| `list_parent_dirs.py` | Prints parent directory structure of the WeChat data folder |
| `list_subfolders.py` | Lists subdirectories within the WeChat data path |
| `search_file_on_disk.py` | Searches for a specific file by name on disk |
| `search_transcriptions.py` | Scans transcription cache for matching text |

## Output Files

| File | Contents |
|---|---|
| `files_inspection.txt` | Output from file message inspection runs |
| `resource_inspection.txt` | Output from resource table inspection |
| `specific_file_msg.txt` | Detailed dump of a specific file message |

---

All scripts assume you have already run `decryptor.py` and have files in the `decrypted/` directory.
