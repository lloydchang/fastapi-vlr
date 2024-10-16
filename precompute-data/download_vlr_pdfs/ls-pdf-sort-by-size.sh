#!/bin/sh -x

# File: precompute-data/download_vlr_pdfs/ls-pdf-sort-by-size.sh

# This script finds all PDF files and sorts them by size in ascending order.

# Navigate to the script's directory.
cd "$(dirname "$0")"

# Find all PDF files, list them with human-readable sizes, and sort by size.
find . -type f -name "*.pdf" -exec ls -lhS {} + | sort -k5,5n
