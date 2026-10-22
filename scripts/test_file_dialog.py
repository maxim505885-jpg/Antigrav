import subprocess
from pathlib import Path

def pick_file_windows(title="Выберите файл облака точек", filter_str="Point Clouds (*.rcs;*.rcp;*.e57;*.las;*.laz;*.ply)|*.rcs;*.rcp;*.e57;*.las;*.laz;*.ply|All Files (*.*)|*.*"):
    ps_script = f"""
    Add-Type -AssemblyName System.Windows.Forms
    $f = New-Object System.Windows.Forms.OpenFileDialog
    $f.Title = '{title}'
    $f.Filter = '{filter_str}'
    if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
        Write-Output $f.FileName
    }}
    """
    res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True)
    out = res.stdout.strip()
    return out if out else None

if __name__ == "__main__":
    print("Windows OpenFileDialog helper compiled successfully.")
