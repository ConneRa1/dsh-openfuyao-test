# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the headless openFuyao sidecar.

Build from the repository root:

    .venv/bin/python -m PyInstaller --noconfirm --clean \
        --distpath build/sidecar-dist --workpath build/pyinstaller \
        scripts/witty-openfuyao-sidecar.spec
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"

# Alembic migrations are data files: the sidecar runs ``upgrade head`` on
# startup, so the version scripts must ship next to the frozen package.
datas = [
    (str(SRC / "witty_service" / "alembic"), "witty_service/alembic"),
]

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.pysqlite",
]
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("alembic")
hiddenimports += collect_submodules("witty_service.sidecar")

analysis = Analysis(
    [str(ROOT / "scripts" / "sidecar_entry.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # The sidecar deliberately does not import the agent runtime. Exclude
        # the largest optional stacks so a packaging regression fails loudly
        # instead of silently producing a 300 MB binary.
        "deepseek_harness",
        "docker",
        "git",
        "apscheduler",
        "witty_agent_server",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="witty-openfuyao-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="witty-openfuyao-sidecar",
)
