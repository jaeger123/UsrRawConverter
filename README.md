# USR/RAW to PNG Converter

A Python tool to convert Siemens/GE ultrasound HDF5 files (`.usr`, `.raw`) to viewable PNG images.

## Background

Ultrasound machines from manufacturers like Siemens and GE store scan data in HDF5 (Hierarchical Data Format version 5) files with `.raw` and `.usr` extensions:

- **`.raw` files** - Contain the actual ultrasound image/scan data
- **`.usr` files** - Contain user settings and configuration (no image data)

This tool extracts the image data and converts it to standard PNG format for viewing.

## Requirements

- Python 3.8+
- Dependencies:
  ```
  h5py
  pillow
  numpy
  ```

## Installation

1. Clone or download this repository

2. Create a virtual environment (recommended):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On macOS/Linux
   # or
   .venv\Scripts\activate     # On Windows
   ```

3. Install dependencies:
   ```bash
   pip install h5py pillow numpy
   ```

## Usage

### Basic Usage

Convert all `.usr`/`.raw` files in a folder:

```bash
python converter.py /path/to/images
```

This creates a `converted/` subfolder with the PNG output.

### Specify Output Folder

```bash
python converter.py /path/to/images /path/to/output
```

### Quiet Mode

For large batches (e.g., 90GB of data), use quiet mode to suppress per-file messages:

```bash
python converter.py /path/to/images --quiet
```

### Examples

```bash
# Convert files in current directory's 'images' folder
python converter.py ./images

# Convert with custom output location
python converter.py ./images ./converted_ultrasounds

# Process large dataset quietly
python converter.py /Volumes/External/UltrasoundData /Volumes/External/Output -q
```

## Output

For each `.raw` file containing image data, the converter creates:

- `{filename}_ultrasound.png` - The main ultrasound scan image (scaled for viewing)
- `{filename}_preview.png` - Preview/titlebar image if available

## How It Works

1. Scans the input folder recursively for `.usr` and `.raw` files
2. Verifies each file is a valid HDF5 file (checks magic bytes)
3. Skips settings-only files (`.usr` files with no image data)
4. Extracts ultrasound data from known HDF5 paths:
   - `MovieGroup1/AcqTissue/RawData/RawDataUnit`
   - Preview images from `PreviewInformation/TitleBarDataGroup/`
5. Converts raw data to PNG with automatic scaling

## File Format Details

The `.raw`/`.usr` files use HDF5 format with the following structure:

```
/MovieGroup1
    /AcqTissue
        /RawData
            /RawDataUnit    <- Main ultrasound image data
    /ViewerTissue
/PreviewInformation
    /TitleBarDataGroup
        /TB_vecBitmapData   <- Preview bitmap (BGRA format)
/FileInfo
/GeometryTestInfo
```

`.usr` files typically only contain:
```
/ReproData      <- Scan settings
/SettingsInfo   <- Configuration
/VersionInfo    <- Version metadata
```

## Troubleshooting

**"Not an HDF5 file" warning**
- The file may be corrupted or is a different format with the same extension

**No image data found**
- The file structure may differ from expected paths
- The file might be a settings-only `.usr` file (this is normal)

**Memory issues with large datasets**
- Process in smaller batches
- Ensure sufficient RAM for large ultrasound files

## License

MIT License - Feel free to use and modify as needed.
