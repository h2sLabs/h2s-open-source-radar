import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import requests

from db import APP_DIR, load_settings

UA = "H2S-Open-Source-Radar/1.0"

HEAVY_MINIMUMS = {
    "작곡·음악 생성": 4 * 1024**3,
    "로컬 LLM": 4 * 1024**3,
    "영상·이미지 AI": 4 * 1024**3,
    "3D·비전": 3 * 1024**3,
    "Stem·오디오 분리": 2 * 1024**3,
    "보컬·가창 합성": 2 * 1024**3,
    "Audio→MIDI·채보": 1024**3,
    "DAW 자동화": 512 * 1024**2,
    "Agent·MCP": 512 * 1024**2,
    "기타 AI": 512 * 1024**2,
}
PERMISSIVE = {"MIT","BSD-2-Clause","BSD-3-Clause","Apache-2.0","ISC","Unlicense","CC0-1.0","Zlib"}
COPYLEFT = {
    "GPL-2.0","GPL-2.0-only","GPL-2.0-or-later","GPL-3.0","GPL-3.0-only","GPL-3.0-or-later",
    "AGPL-3.0","AGPL-3.0-only","AGPL-3.0-or-later","LGPL-2.1","LGPL-3.0"
}

def _sysctl(key, default=""):
    try:
        p = subprocess.run(["/usr/sbin/sysctl","-n",key], capture_output=True, text=True, timeout=3)
        return p.stdout.strip() or default
    except Exception:
        return default

def mac_profile():
    usage = shutil.disk_usage(Path.home())
    mem = int(_sysctl("hw.memsize", "0") or 0)
    cpu = _sysctl("machdep.cpu.brand_string", "") or _sysctl("hw.model", "")
    return {
        "arch": platform.machine() or "unknown",
        "macos": platform.mac_ver()[0] or platform.release(),
        "ram_bytes": mem,
        "free_bytes": usage.free,
        "total_disk_bytes": usage.total,
        "cpu": cpu or ("Apple Silicon" if platform.machine() == "arm64" else "Mac"),
    }

def format_bytes(value):
    value = int(value or 0)
    if value <= 0: return "—"
    x = float(value)
    for unit in ["B","KB","MB","GB","TB"]:
        if x < 1024 or unit == "TB":
            if unit in {"GB","TB"}: return f"{x:.1f} {unit}"
            if unit == "MB": return f"{x:.0f} {unit}"
            return f"{x:.0f} {unit}"
        x /= 1024
    return f"{value} B"

def estimate_install_bytes(repo):
    source = max(0, int(repo.get("repo_size_kb") or 0)) * 1024
    language = (repo.get("language") or "").lower()
    factor = 4.0 if language == "python" else 3.5 if language in {"javascript","typescript"} else 2.5 if language in {"c++","c","rust","go","swift"} else 2.0
    estimate = int(max(source * factor, 180 * 1024**2))
    estimate = max(estimate, HEAVY_MINIMUMS.get(repo.get("category") or "", 512 * 1024**2))
    release_size = int(repo.get("release_asset_size") or 0)
    if release_size > 0:
        estimate = max(estimate, int(release_size * 2.4))
    return estimate

def license_group(spdx):
    spdx = (spdx or "").strip()
    if not spdx: return "undeclared"
    if spdx in PERMISSIVE: return "permissive"
    if spdx in COPYLEFT or "GPL" in spdx: return "copyleft"
    return "declared"

def _norm(text):
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())

def _installed_index():
    names = {}
    for base in [Path("/Applications"), Path.home() / "Applications"]:
        if not base.exists(): continue
        try:
            for p in base.iterdir():
                if p.suffix.lower() == ".app": names[_norm(p.stem)] = str(p)
        except Exception:
            pass

    plugin_roots = [
        Path("/Library/Audio/Plug-Ins/Components"), Path.home()/"Library/Audio/Plug-Ins/Components",
        Path("/Library/Audio/Plug-Ins/VST3"), Path.home()/"Library/Audio/Plug-Ins/VST3",
        Path("/Library/Audio/Plug-Ins/CLAP"), Path.home()/"Library/Audio/Plug-Ins/CLAP",
    ]
    for base in plugin_roots:
        if not base.exists(): continue
        try:
            for p in base.iterdir():
                if p.suffix.lower() in {".component",".vst3",".clap"}:
                    names[_norm(p.stem)] = str(p)
        except Exception:
            pass

    for base in [Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path.home()/".local/bin"]:
        if not base.exists(): continue
        try:
            for p in base.iterdir():
                if p.is_file() or p.is_symlink():
                    names.setdefault(_norm(p.name), str(p))
        except Exception:
            pass

    root = Path(os.path.expanduser(load_settings().get("install_root") or ""))
    if root.exists():
        try:
            for p in root.iterdir(): names[_norm(p.stem)] = str(p)
        except Exception:
            pass
    return names

_INSTALLED_CACHE = {"ts":0.0,"data":{}}

def find_installed(repo, refresh=False):
    now = time.time()
    if refresh or now - _INSTALLED_CACHE["ts"] > 30:
        _INSTALLED_CACHE["data"] = _installed_index()
        _INSTALLED_CACHE["ts"] = now

    managed = (repo.get("install_path") or "").strip()
    if managed and Path(managed).exists():
        return {"installed":True,"path":managed,"source":"H2S"}

    target = _norm(repo.get("name") or "")
    if not target:
        return {"installed":False,"path":"","source":""}
    index = _INSTALLED_CACHE["data"]
    if target in index:
        return {"installed":True,"path":index[target],"source":"Applications"}
    if len(target) >= 6:
        for key, path in index.items():
            if len(key) >= 6 and (target in key or key in target):
                return {"installed":True,"path":path,"source":"Applications"}
    return {"installed":False,"path":"","source":""}

def assess_repo(repo, profile=None):
    profile = profile or mac_profile()
    text = " ".join([repo.get("name") or "", repo.get("description") or "", " ".join(repo.get("topics") or [])]).lower()
    estimate = int(repo.get("installed_size") or 0) or estimate_install_bytes(repo)
    free = int(profile.get("free_bytes") or 0)
    required = int(estimate * 1.2)
    blockers, review = [], []

    if any(x in text for x in ["windows only","windows-only","win32 only","directml only"]):
        blockers.append("Windows-only")
    if any(x in text for x in ["linux only","linux-only","ubuntu only","ubuntu-only"]):
        blockers.append("Linux-only")
    cuda_only = any(x in text for x in ["cuda only","cuda-only","nvidia only","nvidia-only"]) and not any(x in text for x in ["metal","mps","apple silicon","macos","darwin"])
    if cuda_only and profile.get("arch") == "arm64":
        blockers.append("CUDA/NVIDIA-only")
    if any(x in text for x in ["intel only","x86_64 only","x64 only"]) and profile.get("arch") == "arm64":
        review.append("Intel-only build may require Rosetta")

    ram = int(profile.get("ram_bytes") or 0)
    heavy = {"작곡·음악 생성","로컬 LLM","영상·이미지 AI","3D·비전"}
    min_ram = 16*1024**3 if (repo.get("category") or "") in heavy else 8*1024**3
    if ram and ram < min_ram:
        review.append(f"Recommended RAM ≥ {format_bytes(min_ram)}")
    if free and free < required:
        blockers.append(f"Not enough free space ({format_bytes(free)} free, {format_bytes(required)} recommended)")

    explicit_mac = any(x in text for x in ["macos","mac os","darwin","apple silicon","m1","m2","m3","m4","metal","coreml","mlx"])
    broadly_portable = (repo.get("language") or "").lower() in {"python","javascript","typescript","rust","go","swift","c","c++"}
    release_ready = bool(int(repo.get("release_compatible") or 0) and repo.get("release_asset_url") and repo.get("release_install_method"))

    if blockers:
        status, reason = "blocked", " · ".join(blockers)
    elif release_ready:
        status, reason = "ready", (repo.get("release_reason") or "Verified macOS release asset")
    elif review:
        status, reason = "review", " · ".join(review)
    elif explicit_mac or broadly_portable:
        status, reason = "ready", "No obvious Mac compatibility blocker found"
    else:
        status, reason = "review", "Platform requirements are not explicit"

    installed = find_installed(repo)
    return {
        "status":status, "reason":reason, "estimated_bytes":estimate, "required_bytes":required,
        "free_bytes":free, "installed":installed["installed"], "installed_path":installed["path"],
        "installed_source":installed["source"],
        "one_click_ready": status == "ready" and release_ready and not installed["installed"],
        "release_size":int(repo.get("release_asset_size") or 0),
        "license_group":license_group(repo.get("license") or ""),
    }

def _release_headers():
    headers = {"Accept":"application/vnd.github+json","User-Agent":UA,"X-GitHub-Api-Version":"2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN","").strip()
    if token: headers["Authorization"] = f"Bearer {token}"
    return headers

def probe_release(repo, profile=None):
    profile = profile or mac_profile()
    full_name = repo.get("full_name") or ""
    if "/" not in full_name:
        return {"compatible":False,"reason":"Invalid GitHub repository name"}

    response = requests.get(f"https://api.github.com/repos/{full_name}/releases/latest", headers=_release_headers(), timeout=12)
    if response.status_code == 404:
        return {"compatible":False,"reason":"No GitHub release asset available for one-click install"}
    if response.status_code == 403:
        return {"compatible":False,"reason":"GitHub API rate limit reached; try again later"}
    response.raise_for_status()
    payload = response.json()

    arch = (profile.get("arch") or "").lower()
    repo_text = " ".join([repo.get("name") or "", repo.get("description") or "", " ".join(repo.get("topics") or [])]).lower()
    repo_mac_hint = any(x in repo_text for x in ["macos","mac os","darwin","apple silicon","metal","coreml","mlx"])
    candidates = []
    for asset in payload.get("assets") or []:
        name = (asset.get("name") or "").lower()
        if not name or any(x in name for x in ["windows","win32","win64",".exe",".msi","linux","ubuntu",".deb",".rpm","appimage"]):
            continue
        if name.endswith(".dmg"): method = "dmg"
        elif name.endswith(".pkg"): method = "pkg"
        elif name.endswith(".zip"): method = "zip"
        elif name.endswith(".tar.gz") or name.endswith(".tgz"): method = "tar"
        else: continue

        score = 0
        is_mac = any(x in name for x in ["macos","mac-os","darwin","osx","mac_",".dmg",".pkg"])
        arch_match = False
        if is_mac: score += 30
        if arch == "arm64":
            if any(x in name for x in ["arm64","aarch64","apple-silicon","applesilicon"]):
                score += 50; arch_match = True
            if "universal" in name:
                score += 40; arch_match = True
            if any(x in name for x in ["x86_64","amd64","intel"]): score -= 35
        else:
            arch_match = True
        score += 8 if method == "dmg" else 6 if method == "zip" else 4 if method == "pkg" else 0
        candidates.append((score,asset,method,arch_match,is_mac))

    if not candidates:
        return {"compatible":False,"release_name":payload.get("name") or payload.get("tag_name") or "","reason":"No macOS-compatible release asset found"}

    candidates.sort(key=lambda x:x[0], reverse=True)
    score, asset, method, arch_match, is_mac = candidates[0]
    if score < 0:
        return {"compatible":False,"release_name":payload.get("name") or payload.get("tag_name") or "","reason":"Latest release appears to target a different architecture"}
    if not is_mac and not repo_mac_hint:
        return {"compatible":False,"release_name":payload.get("name") or payload.get("tag_name") or "",
                "asset_name":asset.get("name") or "","asset_size":int(asset.get("size") or 0),
                "reason":"Release asset platform is not explicit enough for safe one-click install"}
    if arch == "arm64" and is_mac and not arch_match:
        return {"compatible":False,"release_name":payload.get("name") or payload.get("tag_name") or "",
                "asset_name":asset.get("name") or "","asset_size":int(asset.get("size") or 0),
                "reason":"A macOS release exists, but Apple Silicon/universal support is not explicit"}

    asset_url = asset.get("browser_download_url") or ""
    host = urlparse(asset_url).hostname or ""
    if host not in {"github.com","objects.githubusercontent.com","release-assets.githubusercontent.com"}:
        return {"compatible":False,"reason":"Release asset is not hosted on an approved GitHub host"}

    return {
        "compatible":True, "release_name":payload.get("name") or payload.get("tag_name") or "",
        "asset_name":asset.get("name") or "", "asset_url":asset_url, "asset_size":int(asset.get("size") or 0),
        "install_method":method, "reason":"Verified official GitHub release asset for this Mac",
        "tag_name":payload.get("tag_name") or "",
    }

def _safe_name(text):
    return re.sub(r"[^A-Za-z0-9._ -]+", "-", text or "").strip() or "H2S Tool"

def _download(url, dest, progress=None):
    with requests.get(url, headers={"User-Agent":UA}, stream=True, timeout=60, allow_redirects=True) as response:
        response.raise_for_status()
        final_host = urlparse(response.url).hostname or ""
        if final_host not in {"github.com","objects.githubusercontent.com","release-assets.githubusercontent.com","githubusercontent.com"}:
            raise RuntimeError("Download redirected outside approved GitHub hosts")
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with open(dest,"wb") as f:
            for chunk in response.iter_content(chunk_size=1024*1024):
                if not chunk: continue
                f.write(chunk); done += len(chunk)
                if progress and total: progress(min(70, int(done/total*70)))

def _copy_app(app, install_root):
    install_root.mkdir(parents=True, exist_ok=True)
    dest = install_root / app.name
    if dest.exists(): shutil.rmtree(dest)
    subprocess.run(["/usr/bin/ditto",str(app),str(dest)], check=True)
    return dest

def _find_app(root):
    apps = list(Path(root).rglob("*.app"))
    return apps[0] if apps else None

def _inside(base, target):
    try:
        Path(target).resolve().relative_to(Path(base).resolve())
        return True
    except ValueError:
        return False

def _safe_extract_zip(archive, destination):
    destination = Path(destination)
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            if not _inside(destination, destination / info.filename):
                raise RuntimeError("Unsafe path found in ZIP archive")
        zf.extractall(destination)

def _safe_extract_tar(archive, destination):
    destination = Path(destination)
    with tarfile.open(archive,"r:*") as tf:
        members = []
        for member in tf.getmembers():
            if not _inside(destination, destination / member.name):
                raise RuntimeError("Unsafe path found in TAR archive")
            if member.issym() or member.islnk():
                raise RuntimeError("Archive links are not allowed in one-click installs")
            members.append(member)
        tf.extractall(destination, members=members)

def _dir_size(path):
    path = Path(path)
    if path.is_file(): return path.stat().st_size
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file(): total += p.stat().st_size
        except Exception:
            pass
    return total

def install_release(repo, release_info, progress=None):
    method = release_info.get("install_method") or ""
    url = release_info.get("asset_url") or ""
    if not release_info.get("compatible") or not url or not method:
        raise RuntimeError("No verified one-click install asset")

    install_root = Path(os.path.expanduser(load_settings().get("install_root") or "~/Applications/H2S Tools"))
    install_root.mkdir(parents=True, exist_ok=True)
    work_root = APP_DIR / "downloads"
    work_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="h2s-install-", dir=str(work_root)) as td:
        td = Path(td)
        filename = _safe_name(release_info.get("asset_name") or "download")
        package = td / filename
        if progress: progress(2)
        _download(url, package, progress)
        if progress: progress(74)
        installed_path = None

        if method == "zip":
            expanded = td / "expanded"; expanded.mkdir()
            _safe_extract_zip(package, expanded)
            app = _find_app(expanded)
            if app: installed_path = _copy_app(app, install_root)
            else:
                dest = install_root / _safe_name(repo.get("name") or "tool")
                if dest.exists(): shutil.rmtree(dest)
                shutil.copytree(expanded,dest); installed_path = dest
        elif method == "tar":
            expanded = td / "expanded"; expanded.mkdir()
            _safe_extract_tar(package, expanded)
            app = _find_app(expanded)
            if app: installed_path = _copy_app(app, install_root)
            else:
                dest = install_root / _safe_name(repo.get("name") or "tool")
                if dest.exists(): shutil.rmtree(dest)
                shutil.copytree(expanded,dest); installed_path = dest
        elif method == "dmg":
            mount = None
            try:
                p = subprocess.run(["/usr/bin/hdiutil","attach","-nobrowse","-readonly",str(package)], capture_output=True, text=True, check=True)
                for line in p.stdout.splitlines():
                    if "/Volumes/" in line: mount = Path(line[line.index("/Volumes/"):].strip())
                if not mount: raise RuntimeError("Could not mount DMG")
                app = _find_app(mount)
                if not app: raise RuntimeError("No .app found in DMG")
                installed_path = _copy_app(app, install_root)
            finally:
                if mount: subprocess.run(["/usr/bin/hdiutil","detach",str(mount)], capture_output=True)
        elif method == "pkg":
            pending_root = APP_DIR / "pending-installers"; pending_root.mkdir(parents=True, exist_ok=True)
            pending_pkg = pending_root / filename
            if pending_pkg.exists(): pending_pkg.unlink()
            shutil.copy2(package,pending_pkg)
            subprocess.Popen(["/usr/bin/open",str(pending_pkg)])
            return {"path":str(pending_pkg),"version":release_info.get("tag_name") or "","bytes":pending_pkg.stat().st_size,"pending_system_installer":True}
        else:
            raise RuntimeError(f"Unsupported install method: {method}")

        if progress: progress(96)
        size = _dir_size(installed_path) if installed_path else 0
        if progress: progress(100)
        return {"path":str(installed_path or ""),"version":release_info.get("tag_name") or "","bytes":size,"pending_system_installer":False}
