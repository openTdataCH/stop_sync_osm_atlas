#!/usr/bin/env python3
"""
Simple script to crop an image by 15% from all sides.
"""

from PIL import Image
import os

def crop_image_15_percent(input_path: str, output_path: str):
    """
    Crop 15% from all sides of an image and save the result.
    
    Args:
        input_path: Path to the input image
        output_path: Path where the cropped image will be saved
    """
    # Open the image
    with Image.open(input_path) as img:
        width, height = img.size
        
        # Calculate 15% crop from each side
        left = int(width * 0.15)
        top = int(height * 0.15)
        right = int(width * 0.85)
        bottom = int(height * 0.85)
        
        # Crop the image
        cropped_img = img.crop((left, top, right, bottom))
        
        # Save the cropped image
        cropped_img.save(output_path, optimize=True)
        print(f"Cropped image saved to: {output_path}")

if __name__ == "__main__":
    input_file = "memoire/figures/Example of distance P1 problem.png"
    output_file = "memoire/figures/Example of distance P1 problem_cropped.png"
    
    if os.path.exists(input_file):
        crop_image_15_percent(input_file, output_file)
    else:
        print(f"Input file not found: {input_file}")
