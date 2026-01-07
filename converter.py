#!/usr/bin/env python3
"""
USR/RAW to PNG Converter

Converts Siemens/GE ultrasound HDF5 files (.usr, .raw) to viewable PNG images.
These files are Hierarchical Data Format version 5 (HDF5) containing ultrasound scan data.

Usage:
    python converter.py <input_folder> [output_folder]

If output_folder is not specified, creates a 'converted' subfolder in input_folder.
"""

import os
import sys
import argparse
from pathlib import Path

import h5py
import numpy as np
from PIL import Image


def find_ultrasound_data(hdf_file):
    """
    Search for ultrasound image data in HDF5 file.
    Returns list of (path, dataset) tuples for found image data.
    """
    images = []

    def visitor(name, obj):
        if isinstance(obj, h5py.Dataset):
            shape = obj.shape
            dtype = obj.dtype

            # Look for 2D or 3D uint8 arrays that could be images
            if dtype == np.uint8 and len(shape) >= 2:
                # Check if it's reasonably sized for an image
                if len(shape) == 2 and shape[0] > 50 and shape[1] > 50:
                    images.append((name, 'grayscale_2d'))
                elif len(shape) == 3 and shape[0] >= 1 and shape[1] > 50 and shape[2] > 50:
                    images.append((name, 'grayscale_3d'))
                elif len(shape) == 3 and shape[2] in [3, 4] and shape[0] > 50 and shape[1] > 50:
                    images.append((name, 'color'))

    hdf_file.visititems(visitor)
    return images


def extract_raw_ultrasound(hdf_file):
    """Extract the main ultrasound raw data from the file."""
    # Common paths for raw ultrasound data
    raw_paths = [
        'MovieGroup1/AcqTissue/RawData/RawDataUnit',
        'MovieGroup1/AcqTissue/RawData',
        'RawData/RawDataUnit',
    ]

    for path in raw_paths:
        try:
            data = hdf_file[path][:]
            if data is not None and data.size > 1000:
                # Remove leading singleton dimensions
                while len(data.shape) > 2 and data.shape[0] == 1:
                    data = data[0]
                return data, path
        except (KeyError, ValueError):
            continue

    return None, None


def extract_preview_image(hdf_file):
    """Extract preview/thumbnail image from the file."""
    # Common paths for preview images
    preview_paths = [
        ('PreviewInformation/TitleBarDataGroup/TB_vecBitmapData',
         'PreviewInformation/TitleBarDataGroup/TB_BmpWidth',
         'PreviewInformation/TitleBarDataGroup/TB_BmpHeight',
         'PreviewInformation/TitleBarDataGroup/TB_BmpBitsPerPixel'),
    ]

    for data_path, width_path, height_path, bpp_path in preview_paths:
        try:
            data = hdf_file[data_path][:]
            width = int(hdf_file[width_path][0])
            height = int(hdf_file[height_path][0])
            bpp = int(hdf_file[bpp_path][0])

            if bpp == 32:
                # BGRA format
                img_array = np.frombuffer(data, dtype=np.uint8).reshape((height, width, 4))
                img_array = img_array[:, :, [2, 1, 0, 3]]  # BGRA to RGBA
                img_array = np.flipud(img_array)  # BMP is bottom-up
                return img_array, 'RGBA', data_path
            elif bpp == 24:
                # BGR format
                img_array = np.frombuffer(data, dtype=np.uint8).reshape((height, width, 3))
                img_array = img_array[:, :, ::-1]  # BGR to RGB
                img_array = np.flipud(img_array)
                return img_array, 'RGB', data_path
        except (KeyError, ValueError) as e:
            continue

    return None, None, None


def enhance_ultrasound_image(img_array, apply_clahe=True):
    """
    Enhance ultrasound image for better visualization.
    """
    # Normalize to 0-255 range
    img_min = img_array.min()
    img_max = img_array.max()

    if img_max > img_min:
        normalized = ((img_array - img_min) / (img_max - img_min) * 255).astype(np.uint8)
    else:
        normalized = img_array.astype(np.uint8)

    return normalized


def is_settings_file(hdf_file):
    """
    Check if the HDF5 file is a settings/config file (no image data).
    .usr files typically contain ReproData, SettingsInfo, VersionInfo only.
    """
    root_keys = set(hdf_file.keys())
    settings_only_keys = {'ReproData', 'SettingsInfo', 'VersionInfo'}

    # If file only contains settings-related groups, it's a settings file
    if root_keys.issubset(settings_only_keys):
        return True
    return False


def convert_file(input_path, output_dir, verbose=True):
    """
    Convert a single .usr or .raw file to PNG.
    Returns tuple: (list of output file paths, is_settings_file boolean)
    """
    output_files = []
    input_path = Path(input_path)
    output_dir = Path(output_dir)

    base_name = input_path.stem

    try:
        with h5py.File(input_path, 'r') as f:
            # Check if this is a settings-only file
            if is_settings_file(f):
                if verbose:
                    print(f"  Skipping: Settings/config file (no image data)")
                return output_files, True  # Return flag indicating settings file
            # Try to extract raw ultrasound data
            raw_data, raw_path = extract_raw_ultrasound(f)

            if raw_data is not None:
                if verbose:
                    print(f"  Found raw ultrasound data: {raw_data.shape}")

                # Enhance and save
                enhanced = enhance_ultrasound_image(raw_data)
                img = Image.fromarray(enhanced)

                # Scale up for better viewing (ultrasound scans are often narrow)
                # Maintain aspect ratio but make it reasonable size
                width, height = img.size
                if width < 800:
                    scale = 800 / width
                    new_size = (int(width * scale), int(height * scale))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)

                output_path = output_dir / f"{base_name}_ultrasound.png"
                img.save(output_path)
                output_files.append(output_path)
                if verbose:
                    print(f"  Saved: {output_path}")

            # Try to extract preview/titlebar image
            preview_data, mode, preview_path = extract_preview_image(f)

            if preview_data is not None:
                if verbose:
                    print(f"  Found preview image: {preview_data.shape}")

                img = Image.fromarray(preview_data, mode)
                output_path = output_dir / f"{base_name}_preview.png"
                img.save(output_path)
                output_files.append(output_path)
                if verbose:
                    print(f"  Saved: {output_path}")

            # If neither worked, try to find any image-like data
            if not output_files:
                images = find_ultrasound_data(f)
                for img_path, img_type in images[:3]:  # Limit to first 3
                    try:
                        data = f[img_path][:]

                        if img_type == 'grayscale_3d':
                            data = data[0] if data.shape[0] == 1 else data

                        if len(data.shape) == 2:
                            img = Image.fromarray(data)
                        else:
                            img = Image.fromarray(data)

                        safe_name = img_path.replace('/', '_')
                        output_path = output_dir / f"{base_name}_{safe_name}.png"
                        img.save(output_path)
                        output_files.append(output_path)
                        if verbose:
                            print(f"  Saved: {output_path}")
                    except Exception as e:
                        if verbose:
                            print(f"  Warning: Could not extract {img_path}: {e}")

    except Exception as e:
        if verbose:
            print(f"  Error processing {input_path}: {e}")

    return output_files, False  # Not a settings file


def convert_folder(input_folder, output_folder=None, verbose=True):
    """
    Convert all .usr and .raw files in a folder to PNG.

    Args:
        input_folder: Path to folder containing .usr/.raw files
        output_folder: Path to output folder (default: input_folder/converted)
        verbose: Print progress messages

    Returns:
        dict with 'converted', 'skipped', 'failed' counts
    """
    input_folder = Path(input_folder)

    if output_folder is None:
        output_folder = input_folder / 'converted'
    else:
        output_folder = Path(output_folder)

    output_folder.mkdir(parents=True, exist_ok=True)

    # Find all .usr and .raw files
    target_files = []
    for ext in ['*.usr', '*.raw', '*.USR', '*.RAW']:
        target_files.extend(input_folder.rglob(ext))

    # Remove duplicates and sort
    target_files = sorted(set(target_files))

    if verbose:
        print(f"Found {len(target_files)} .usr/.raw files in {input_folder}")
        print(f"Output folder: {output_folder}")
        print()

    stats = {'converted': 0, 'skipped': 0, 'failed': 0, 'output_files': []}

    for i, file_path in enumerate(target_files, 1):
        if verbose:
            print(f"[{i}/{len(target_files)}] Processing: {file_path.name}")

        # Check if it's actually an HDF5 file
        try:
            with open(file_path, 'rb') as f:
                signature = f.read(8)

            if signature[:4] != b'\x89HDF':
                if verbose:
                    print(f"  Skipping: Not an HDF5 file")
                stats['skipped'] += 1
                continue
        except Exception as e:
            if verbose:
                print(f"  Skipping: Cannot read file ({e})")
            stats['skipped'] += 1
            continue

        # Convert the file
        output_files, is_settings = convert_file(file_path, output_folder, verbose)

        if is_settings:
            stats['skipped'] += 1  # Settings files are skipped
        elif output_files:
            stats['converted'] += 1
            stats['output_files'].extend(output_files)
        else:
            stats['failed'] += 1
            if verbose:
                print(f"  Failed: No image data found")

        if verbose:
            print()

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Convert Siemens/GE ultrasound HDF5 files (.usr, .raw) to PNG images.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python converter.py ./images
    python converter.py ./images ./output
    python converter.py /path/to/90gb/folder /path/to/output --quiet
        """
    )
    parser.add_argument('input_folder', help='Folder containing .usr/.raw files')
    parser.add_argument('output_folder', nargs='?', help='Output folder (default: input_folder/converted)')
    parser.add_argument('-q', '--quiet', action='store_true', help='Suppress progress messages')

    args = parser.parse_args()

    if not os.path.isdir(args.input_folder):
        print(f"Error: '{args.input_folder}' is not a valid directory")
        sys.exit(1)

    stats = convert_folder(
        args.input_folder,
        args.output_folder,
        verbose=not args.quiet
    )

    print("=" * 50)
    print(f"Conversion complete!")
    print(f"  Converted: {stats['converted']} files")
    print(f"  Skipped:   {stats['skipped']} files")
    print(f"  Failed:    {stats['failed']} files")
    print(f"  Total PNG files created: {len(stats['output_files'])}")


if __name__ == '__main__':
    main()
