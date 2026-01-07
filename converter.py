#!/usr/bin/env python3
"""
USR/RAW to PNG Converter

Converts Siemens/GE ultrasound HDF5 files (.usr, .raw) to viewable PNG images.
These files are Hierarchical Data Format version 5 (HDF5) containing ultrasound scan data.

Usage:
    python converter.py <input_folder> [output_folder]
    python converter.py <input_folder> [output_folder] --copy-jpeg

If output_folder is not specified, creates a 'converted' subfolder in input_folder.
"""

import os
import sys
import shutil
import argparse
from pathlib import Path

import h5py
import numpy as np
from PIL import Image
from tqdm import tqdm


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


def convert_file(input_path, output_dir, relative_path=None, verbose=True):
    """
    Convert a single .usr or .raw file to PNG.

    Args:
        input_path: Path to the input file
        output_dir: Base output directory
        relative_path: Relative path from input root (preserves folder structure)
        verbose: Print progress messages

    Returns tuple: (list of output file paths, is_settings_file boolean)
    """
    output_files = []
    input_path = Path(input_path)
    output_dir = Path(output_dir)

    # If relative path provided, preserve folder structure
    if relative_path:
        file_output_dir = output_dir / relative_path.parent
        file_output_dir.mkdir(parents=True, exist_ok=True)
    else:
        file_output_dir = output_dir

    base_name = input_path.stem

    try:
        with h5py.File(input_path, 'r') as f:
            # Check if this is a settings-only file
            if is_settings_file(f):
                if verbose:
                    tqdm.write(f"  Skipping: Settings/config file (no image data)")
                return output_files, True  # Return flag indicating settings file
            # Try to extract raw ultrasound data
            raw_data, raw_path = extract_raw_ultrasound(f)

            if raw_data is not None:
                if verbose:
                    tqdm.write(f"  Found raw ultrasound data: {raw_data.shape}")

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

                output_path = file_output_dir / f"{base_name}_ultrasound.png"
                img.save(output_path)
                output_files.append(output_path)
                if verbose:
                    tqdm.write(f"  Saved: {output_path}")

            # Try to extract preview/titlebar image
            preview_data, mode, preview_path = extract_preview_image(f)

            if preview_data is not None:
                if verbose:
                    tqdm.write(f"  Found preview image: {preview_data.shape}")

                img = Image.fromarray(preview_data, mode)
                output_path = file_output_dir / f"{base_name}_preview.png"
                img.save(output_path)
                output_files.append(output_path)
                if verbose:
                    tqdm.write(f"  Saved: {output_path}")

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
                        output_path = file_output_dir / f"{base_name}_{safe_name}.png"
                        img.save(output_path)
                        output_files.append(output_path)
                        if verbose:
                            tqdm.write(f"  Saved: {output_path}")
                    except Exception as e:
                        if verbose:
                            tqdm.write(f"  Warning: Could not extract {img_path}: {e}")

    except Exception as e:
        if verbose:
            tqdm.write(f"  Error processing {input_path}: {e}")

    return output_files, False  # Not a settings file


def copy_jpeg_files(input_folder, output_folder, verbose=True):
    """
    Find and copy all JPEG files from input folder to output folder.
    Preserves relative folder structure.

    Returns:
        dict with 'copied' count and 'files' list
    """
    input_folder = Path(input_folder)
    output_folder = Path(output_folder)

    # Find all JPEG files
    jpeg_files = []
    for ext in ['*.jpg', '*.jpeg', '*.JPG', '*.JPEG']:
        jpeg_files.extend(input_folder.rglob(ext))

    jpeg_files = sorted(set(jpeg_files))

    stats = {'copied': 0, 'files': []}

    if not jpeg_files:
        return stats

    if verbose:
        print(f"Found {len(jpeg_files)} JPEG files to copy")

    # Create progress bar for JPEG copying
    pbar = tqdm(jpeg_files, desc="Copying JPEGs", unit="file", disable=False)

    for file_path in pbar:
        try:
            # Preserve relative path structure
            rel_path = file_path.relative_to(input_folder)
            dest_path = output_folder / rel_path

            # Update progress bar
            pbar.set_postfix_str(f"{rel_path.name[:30]}")

            # Create parent directories if needed
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Copy the file
            shutil.copy2(file_path, dest_path)
            stats['copied'] += 1
            stats['files'].append(dest_path)

            if verbose:
                tqdm.write(f"Copied: {rel_path}")

        except Exception as e:
            if verbose:
                tqdm.write(f"Failed to copy {file_path.name}: {e}")

    return stats


def convert_folder(input_folder, output_folder=None, copy_jpeg=False, delete_source=False, verbose=True):
    """
    Convert all .usr and .raw files in a folder to PNG.

    Args:
        input_folder: Path to folder containing .usr/.raw files
        output_folder: Path to output folder (default: input_folder/converted)
        copy_jpeg: If True, also copy JPEG files to output folder
        delete_source: If True, delete source .raw/.usr files after successful conversion
        verbose: Print progress messages

    Returns:
        dict with 'converted', 'skipped', 'failed', 'jpeg_copied', 'deleted' counts
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

    stats = {'converted': 0, 'skipped': 0, 'failed': 0, 'jpeg_copied': 0, 'deleted': 0, 'output_files': []}

    # Create progress bar
    pbar = tqdm(target_files, desc="Converting", unit="file", disable=False)

    for file_path in pbar:
        # Calculate relative path from input folder to preserve structure
        try:
            relative_path = file_path.relative_to(input_folder)
        except ValueError:
            relative_path = Path(file_path.name)

        # Update progress bar description
        pbar.set_postfix_str(f"{relative_path.name[:30]}")

        if verbose:
            tqdm.write(f"Processing: {relative_path}")

        # Check if it's actually an HDF5 file
        try:
            with open(file_path, 'rb') as f:
                signature = f.read(8)

            if signature[:4] != b'\x89HDF':
                if verbose:
                    tqdm.write(f"  Skipping: Not an HDF5 file")
                stats['skipped'] += 1
                continue
        except Exception as e:
            if verbose:
                tqdm.write(f"  Skipping: Cannot read file ({e})")
            stats['skipped'] += 1
            continue

        # Convert the file (pass relative_path to preserve folder structure)
        output_files, is_settings = convert_file(file_path, output_folder, relative_path, verbose)

        if is_settings:
            stats['skipped'] += 1  # Settings files are skipped
            # Delete settings files too if delete_source is enabled
            if delete_source:
                try:
                    file_path.unlink()
                    stats['deleted'] += 1
                    if verbose:
                        tqdm.write(f"  Deleted: {file_path.name}")
                except Exception as e:
                    if verbose:
                        tqdm.write(f"  Warning: Could not delete {file_path.name}: {e}")
        elif output_files:
            stats['converted'] += 1
            stats['output_files'].extend(output_files)
            # Delete source file after successful conversion
            if delete_source:
                try:
                    file_path.unlink()
                    stats['deleted'] += 1
                    if verbose:
                        tqdm.write(f"  Deleted: {file_path.name}")
                except Exception as e:
                    if verbose:
                        tqdm.write(f"  Warning: Could not delete {file_path.name}: {e}")
        else:
            stats['failed'] += 1
            if verbose:
                tqdm.write(f"  Failed: No image data found")

    # Copy JPEG files if requested
    if copy_jpeg:
        if verbose:
            print()
            print("Copying JPEG files...")
        jpeg_stats = copy_jpeg_files(input_folder, output_folder, verbose)
        stats['jpeg_copied'] = jpeg_stats['copied']
        stats['output_files'].extend(jpeg_stats['files'])

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
    python converter.py ./images --copy-jpeg    # Also copy JPEG files
        """
    )
    parser.add_argument('input_folder', help='Folder containing .usr/.raw files')
    parser.add_argument('output_folder', nargs='?', help='Output folder (default: input_folder/converted)')
    parser.add_argument('-q', '--quiet', action='store_true', help='Suppress progress messages')
    parser.add_argument('-j', '--copy-jpeg', action='store_true',
                        help='Also copy JPEG files to output folder')
    parser.add_argument('-d', '--delete-source', action='store_true',
                        help='Delete source .raw/.usr files after successful conversion')

    args = parser.parse_args()

    if not os.path.isdir(args.input_folder):
        print(f"Error: '{args.input_folder}' is not a valid directory")
        sys.exit(1)

    stats = convert_folder(
        args.input_folder,
        args.output_folder,
        copy_jpeg=args.copy_jpeg,
        delete_source=args.delete_source,
        verbose=not args.quiet
    )

    print("=" * 50)
    print(f"Conversion complete!")
    print(f"  RAW files converted: {stats['converted']}")
    print(f"  Files skipped:       {stats['skipped']}")
    print(f"  Files failed:        {stats['failed']}")
    if args.copy_jpeg:
        print(f"  JPEGs copied:        {stats['jpeg_copied']}")
    if args.delete_source:
        print(f"  Source files deleted:{stats['deleted']}")
    print(f"  Total output files:  {len(stats['output_files'])}")


if __name__ == '__main__':
    main()
