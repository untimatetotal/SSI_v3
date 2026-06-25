#!/bin/bash
apt-get update -y
apt-get install -y tesseract-ocr tesseract-ocr-tha tesseract-ocr-eng
pip install -r requirements.txt