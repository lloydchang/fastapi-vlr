#!/bin/sh -x

cd $(dirname $0)

find . -type f -exec ls -lhS {} + | sort -k5,5n
