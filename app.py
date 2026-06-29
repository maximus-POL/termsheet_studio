from __future__ import annotations

import streamlit as st


def main() -> None:
    st.set_page_config(page_title="Termsheet Studio", layout="wide")
    st.switch_page("pages/1_Product.py")


if __name__ == "__main__":
    main()
