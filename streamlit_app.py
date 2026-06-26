from __future__ import annotations

import streamlit as st


def main() -> None:
    st.set_page_config(page_title="Termsheet Studio", layout="wide")
    st.title("Termsheet Studio")
    st.write(
        "Use the pages in the sidebar to parse a single termsheet or browse saved products."
    )
    st.info("Start with Product to upload, edit, save, and export one termsheet.")


if __name__ == "__main__":
    main()
