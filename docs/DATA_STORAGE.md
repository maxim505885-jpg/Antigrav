# SCAN storage location

By default, SCAN stores its database, projects, derived point clouds and exports under `%LOCALAPPDATA%\ScanStudio\data`. Large FARO jobs may require a different drive with more free space.

To choose another local, removable or network folder, close SCAN and create `%LOCALAPPDATA%\ScanStudio\data-root.txt`. Put one absolute path on the first line, for example `D:\SCAN\Data` or `\\server\share\SCAN\Data`, then start SCAN again. The app creates the directory if it is writable. A missing or inaccessible drive stops startup with an error instead of silently falling back to C:.

The `S2B_DATA_DIR` Windows environment variable overrides `data-root.txt` and is useful for managed deployments. The existing default database and project files are not moved automatically: changing the root opens a separate data store. Keep SCAN stopped while a qualified migration or backup is performed; do not copy or overwrite the original FARO scans.

Before a full-resolution import, check free space in the selected directory. The importer performs its own preflight and can reject the job if the available space is insufficient.
