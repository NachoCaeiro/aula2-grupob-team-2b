# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['app.py'],
    pathex=[],  # PyInstaller usually sets this to the directory of the spec file.
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
        ('database', 'database') # This includes the database directory.
                                 # If the DB file itself needs to be bundled (e.g., a pre-populated one),
                                 # specify it directly: ('database/clinic.db', 'database')
                                 # However, our app.py logic aims to create it in/near exe_dir.
                                 # Bundling the 'database' FOLDER ensures it's created if app.py's logic depends on it.
    ],
    hiddenimports=[], # Add common Flask related ones if needed: e.g. 'jinja2.ext', 'werkzeug.serving'
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='GestorClinica',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
