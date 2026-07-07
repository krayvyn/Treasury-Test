from __future__ import annotations

import io
import json
from typing import Any

import pandas as pd
import streamlit as st

from label_review.batch import review_one
from label_review.rules import GOVERNMENT_WARNING_EXACT


st.set_page_config(page_title="TTB Label Review Prototype", layout="wide")


def default_application() -> dict[str, str]:
    return {
        "brand_name": "OLD TOM DISTILLERY",
        "class_type": "Kentucky Straight Bourbon Whiskey",
        "abv": "45% Alc./Vol. (90 Proof)",
        "net_contents": "750 mL",
    }


def render_check_table(result: dict[str, Any]) -> None:
    checks_df = pd.DataFrame(result["checks"])
    st.dataframe(
        checks_df[["field", "status", "expected", "actual", "notes"]],
        use_container_width=True,
        hide_index=True,
    )


def parse_application_csv(uploaded_csv: io.BytesIO) -> pd.DataFrame:
    df = pd.read_csv(uploaded_csv)
    required = {"filename", "brand_name", "class_type", "abv", "net_contents"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Application CSV missing columns: {', '.join(sorted(missing))}")
    return df


st.title("TTB Label Compliance Assistant (Prototype)")
st.caption(
    "Standalone proof-of-concept for fast, agent-friendly label checks. "
    "No direct COLA integration."
)

with st.expander("What this checks", expanded=False):
    st.markdown(
        "- Brand name (fuzzy, case-insensitive)\n"
        "- Class/type designation (fuzzy)\n"
        "- ABV value\n"
        "- Net contents\n"
        "- Government warning statement exactness\n"
        "\n**Required warning text:**"
    )
    st.code(GOVERNMENT_WARNING_EXACT)

mode = st.radio("Mode", ["Single Label Review", "Batch Review"], horizontal=True)

if mode == "Single Label Review":
    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("Application Data")
        app_data = default_application()
        app_data["brand_name"] = st.text_input("Brand Name", app_data["brand_name"])
        app_data["class_type"] = st.text_input("Class/Type", app_data["class_type"])
        app_data["abv"] = st.text_input("ABV", app_data["abv"])
        app_data["net_contents"] = st.text_input("Net Contents", app_data["net_contents"])

    with col2:
        st.subheader("Label Image")
        img_file = st.file_uploader("Upload a label image", type=["png", "jpg", "jpeg", "tiff"])
        run = st.button("Run Compliance Check", type="primary", use_container_width=True)

    if run:
        if not img_file:
            st.error("Please upload a label image.")
        else:
            try:
                result = review_one(img_file, app_data)
                status = result["decision"]
                elapsed_s = result["elapsed_ms"] / 1000.0
                if status == "PASS":
                    st.success(f"Decision: PASS ({elapsed_s:.2f}s)")
                elif status == "NEEDS_AGENT_REVIEW":
                    st.warning(f"Decision: NEEDS_AGENT_REVIEW ({elapsed_s:.2f}s)")
                else:
                    st.error(f"Decision: REJECT ({elapsed_s:.2f}s)")

                render_check_table(result)
                with st.expander("OCR text"):
                    st.text(result["ocr_text"])
            except Exception as exc:
                st.error(str(exc))

else:
    st.subheader("Batch Review")
    st.markdown(
        "Upload many label images plus one CSV that maps each image file name to application fields."
    )
    application_csv = st.file_uploader(
        "Application CSV",
        type=["csv"],
        help="Required columns: filename, brand_name, class_type, abv, net_contents",
    )
    image_files = st.file_uploader(
        "Label images",
        type=["png", "jpg", "jpeg", "tiff"],
        accept_multiple_files=True,
    )
    run_batch = st.button("Run Batch", type="primary")

    if run_batch:
        if not application_csv or not image_files:
            st.error("Upload both the application CSV and at least one image.")
        else:
            try:
                app_df = parse_application_csv(application_csv)
                apps = {row["filename"]: row.to_dict() for _, row in app_df.iterrows()}

                results: list[dict[str, Any]] = []
                for file in image_files:
                    app = apps.get(file.name)
                    if not app:
                        results.append(
                            {
                                "filename": file.name,
                                "decision": "SKIPPED",
                                "elapsed_ms": 0,
                                "reason": "No matching row in application CSV",
                                "checks_json": "[]",
                            }
                        )
                        continue

                    result = review_one(file, app)
                    results.append(
                        {
                            "filename": file.name,
                            "decision": result["decision"],
                            "elapsed_ms": result["elapsed_ms"],
                            "reason": "",
                            "checks_json": json.dumps(result["checks"]),
                        }
                    )

                out_df = pd.DataFrame(results)
                st.dataframe(out_df, use_container_width=True, hide_index=True)

                csv_bytes = out_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "Download Batch Results CSV",
                    data=csv_bytes,
                    file_name="ttb_label_batch_results.csv",
                    mime="text/csv",
                )
            except Exception as exc:
                st.error(str(exc))
