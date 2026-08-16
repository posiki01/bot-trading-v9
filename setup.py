#!/usr/bin/env python3
"""
setup.py - Setup para el Bot de Trading V9.0
"""

from setuptools import setup, find_packages

setup(
    name="bot-trading-v9",
    version="9.0.0",
    description="Bot de Trading Cuantitativo V9.0",
    author="Trading Bot",
    packages=find_packages(),
    install_requires=[
        "MetaTrader5>=5.0.45",
        "pandas>=2.0.0",
        "numpy>=1.24.0",
        "scikit-learn>=1.3.0",
        "requests>=2.31.0",
        "feedparser>=6.0.10",
        "python-dotenv>=1.0.0",
        "colorama>=0.4.6",
    ],
    extras_require={
        "dev": [
            "pytest>=7.4.0",
            "pytest-cov>=4.1.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
            "mypy>=1.0.0",
            "isort>=5.12.0",
            "pylint>=2.17.0",
        ],
        "notifications": [
            "python-telegram-bot>=20.0",
        ],
        "visualization": [
            "matplotlib>=3.7.0",
        ],
    },
    python_requires=">=3.9",
    entry_points={
        "console_scripts": [
            "bot-trading=main:main",
        ],
    },
)