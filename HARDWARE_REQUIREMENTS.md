# Grocery Tracker: Hardware & OS Requirements

This document outlines the hardware specifications and Operating System requirements for running the Grocery Tracker application.

Because the app supports both **Local AI Vision Models** (via LM Studio/Ollama) and **Cloud API Models** (via Google Gemini API) for receipt processing, the hardware requirements vary drastically depending on your chosen privacy setup.

## Deployment Matrix

| Setup Type | AI Processing | OS Options | WSL2 Required? | RAM | CPU | GPU (VRAM) | Storage |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Budget / Cloud** | Google Gemini API | Win, Mac, Linux | No (Native Python works) | 4GB - 8GB | Any Dual-Core (10yrs old+) | None (Integrated OK) | 128GB SSD |
| **Standard Local** | Local LM Studio (2B Vision) | Win, Linux, Mac | Optional (Win/WSL2) | 16GB | Modern 4-Core (Ryzen 5 / i5) | 6GB+ Dedicated VRAM | 256GB NVMe |
| **Pro Local** | Local LM Studio (8B Vision) | Win, Linux, Mac | Optional (Win/WSL2) | 32GB | Modern 6-Core+ (Ryzen 7 / i7) | 12GB+ Dedicated VRAM | 512GB NVMe |
| **Apple Silicon** | Local LM Studio (8B Vision) | macOS (M-Series) | No (Native macOS Unix) | 18GB+ (Unified) | Apple M2/M3/M4 Pro/Max | Shared with System RAM | 512GB NVMe |

## Option 1: Low-end Specs (API-Only Mode)
By routing receipt OCR to the Google Gemini API, the local hardware handles only the lightweight Python FastAPI server, the SQLite database, and the web frontend.
- **Ideal for**: Old laptops, Raspberry Pi (Zero 2W, 4, 5 — tested), basic headless servers.
- **OS Notes**: Any OS works. If using Windows on very old hardware, avoiding WSL2 and running Python natively is recommended to save RAM. Alternatively, replacing Windows 11 with a lightweight Linux distribution (like Linux Mint XFCE or Ubuntu Server) will free up significant resources.

## Option 2: The Local Privacy Specs (LM Studio / Ollama)
If you want total privacy by running Qwen2-VL or IBM Granite Vision locally, your computer must act as an AI inference server.
- **Memory is King**: An 8B vision model quantized to 4-bit consumes ~5GB of memory at rest, spiking heavily during image encoding. 32GB of system RAM gives your OS, web server, and the model plenty of breathing room without paging to disk.
- **Context Length**: The prompt and image require significant context window. Ensure your LM Studio model is configured with a context length (`n_ctx`) of at least `4096` or `8192` to avoid `Model reloaded` (HTTP 400) errors during inference.
- **GPU Acceleration**: A dedicated NVIDIA GPU (RTX 3060, 4060, 4070) is highly recommended. CPU-only vision inference is generally too slow for a pleasant user experience (often taking minutes per receipt).
- **The Apple Silicon Advantage**: MacBooks with M1/M2/M3 chips use Unified Memory. An 18GB+ MacBook Pro can effortlessly allocate massive chunks of system memory directly to its integrated GPU, rivaling bulky desktop GPUs for local AI inference.

## A Note on Windows Subsystem for Linux (WSL2)
WSL2 is fantastic for development on Windows, but it runs a Hyper-V virtual machine that aggressively caches memory (often seen as a massive `vmmem` process in Task Manager).

If you are running the API-Only mode on a laptop with limited RAM (e.g., 8GB), WSL2 might consume too much memory.

- **The RAM Fix**: You can cap WSL2's memory usage by creating a `.wslconfig` file in your Windows user folder (e.g., `C:\Users\YourName\.wslconfig`) and adding:
  ```ini
  [wsl2]
  memory=2GB
  ```
- **The Storage Fix**: The WSL2 virtual disk (`ext4.vhdx`) expands dynamically but does not shrink automatically when you delete files inside Ubuntu. You must periodically compact it using the Windows `diskpart` utility to reclaim lost gigabytes.
- **Alternatives to WSL2**: If WSL2 is too heavy, you can use **WSL 1** (a lightweight translation layer instead of a VM — note that WSL 1 has slower Linux filesystem I/O, which may affect database write performance), or simply run the Python backend natively in Windows PowerShell.

---

## Raspberry Pi Deployment

The Grocery Tracker runs well on Raspberry Pi hardware (A Raspberry Pi Zero 2 W) when used in **API-only or LAN-inference mode**. The Pi handles the lightweight FastAPI server and SQLite database; all AI inference happens either in the cloud (Gemini API) or on a separate, more powerful machine running LM Studio.

### Pi Compatibility Matrix

| Model | RAM | 64-bit OS? | API Mode | LM Studio (LAN) | Ollama (on-device) | LM Studio (x86 only) |
|:---|:---|:---|:---|:---|:---|:---|
| **Zero 2 W** | 512MB | No (32-bit default) | ⚠️ Tight | ✅ Works | ❌ No (32-bit) | ❌ No |
| **Zero 2 W** | 512MB | Yes (64-bit OS) | ⚠️ Tight | ✅ Works | ⚠️ Tiny models only | ❌ No |
| **Pi 3B / 3B+** | 1GB | Yes | ✅ OK | ✅ Works | ⚠️ Tiny models only | ❌ No |
| **Pi 4 (2GB)** | 2GB | Yes | ✅ Good | ✅ Works | ⚠️ Small models only | ❌ No |
| **Pi 4 (4GB / 8GB)** | 4–8GB | Yes | ✅ Great | ✅ Works | ✅ Qwen2.5-VL 2B / Qwen2-VL 2B | ❌ No |
| **Pi 5 (4GB / 8GB)** | 4–8GB | Yes | ✅ Great | ✅ Works | ✅ Qwen2.5-VL 2B / Qwen2-VL 2B | ❌ No |

> [!NOTE]
> **LM Studio does not run on any Raspberry Pi.** It requires x86-64 or Apple Silicon. However, you can run LM Studio on a desktop PC or MacBook and point the Pi at it over your local network.

### Option A: Gemini API Mode (Recommended for Zero 2 W)

The Pi makes HTTPS requests to Google's servers for all OCR work. No local AI compute required.

```bash
# .env
GEMINI_API_KEY=your_key_here
OCR_BACKEND=gemini
```

**RAM footprint at idle:** ~150–200MB — workable on 512MB, though PDF conversion (`pdf2image`) can spike usage. Stick to JPG/PNG receipt images on the Zero 2 W to avoid OOM.

### Option B: LM Studio on Your Desktop, Pi as Thin Client

Run LM Studio on your main PC or Mac, enable the local server, and point the Pi at it over your LAN. A wired Ethernet connection is strongly preferred over Wi-Fi for image uploads — large receipt images can be slow or time out on a congested wireless link.

```bash
# .env on the Pi — replace with your desktop's local IP
OCR_BACKEND=local
OCR_BACKEND_URL=http://192.168.1.42:1234/v1
OCR_MODEL=qwen/qwen2.5-vl-7b   # model ID varies — use the exact string shown in LM Studio's model list
```

The Pi sends the receipt image to your desktop for inference and receives the structured JSON response. The Pi itself does zero AI computation — it's just an HTTP client.

**To find your desktop's LAN IP:**
- Linux/Mac: `ip addr` or `ifconfig`
- Windows: `ipconfig` → look for the `192.168.x.x` address

**In LM Studio:** enable the local server (default port 1234) and make sure your desktop's firewall allows inbound connections on that port from the Pi.

### Option C: Ollama on Pi 4 / Pi 5 (On-Device, 64-bit OS Required)

For fully offline, on-device inference on a Pi 4 (4GB+) or Pi 5:

```bash
# Install Ollama (requires 64-bit Raspberry Pi OS)
curl -fsSL https://ollama.com/install.sh | sh

# Pull a supported vision model
ollama pull qwen2.5-vl:2b   # ~1.5GB download

# .env on the Pi
OCR_BACKEND=local
OCR_BACKEND_URL=http://127.0.0.1:11434/v1
OCR_MODEL=qwen2.5-vl:2b
```

> [!WARNING]
> Inference on a Pi 4/5 (CPU only, no GPU) will be **significantly slower** than on a desktop — expect 30–120 seconds per receipt depending on the model and image size. The 2B parameter models are the practical limit for on-device Pi use.

### General Pi Setup Notes

**Use 64-bit Raspberry Pi OS** even if you're not running local models. Some Python packages (`numpy`, `Pillow`, `pdfplumber`) have better wheel availability for `aarch64` than for `armhf` (32-bit).

**PDF processing on low-RAM Pis**: `pdf2image` converts each PDF page to a full-resolution PIL image in RAM before sending it to the OCR model. On 512MB–1GB systems, multi-page PDFs may cause OOM errors. Workaround: configure a lower DPI in the OCR service, or pre-convert PDFs to single JPGs on a desktop before uploading.

**SQLite on SD card**: Works fine for normal use. To reduce write wear and improve performance, move the database to a USB SSD or external drive:
```bash
# In .env
DATABASE_URL=sqlite:////mnt/usb/grocery.db
```

**Swap space**: Add a small swap file (512MB–1GB) as a safety net to prevent OOM crashes:
```bash
sudo dphys-swapfile swapoff
sudo nano /etc/dphys-swapfile   # set CONF_SWAPSIZE=512
sudo dphys-swapfile setup && sudo dphys-swapfile swapon
```

### Quick Start on Pi (API Mode)

```bash
# Install system dependencies
sudo apt update && sudo apt install -y python3 python3-pip pipx poppler-utils libmagic1

# Install uv
pipx install uv

# Clone and configure
git clone https://github.com/smcgazz/grocery-tracker.git
cd grocery-tracker
cp .env.example .env
nano .env   # add GEMINI_API_KEY — get yours free at https://aistudio.google.com

# Run
cd backend
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Access the app from any device on your network at `http://<pi-ip-address>:8000`.
