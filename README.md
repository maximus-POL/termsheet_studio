# termsheet_uploader

Local Python MVP for turning PDF termsheets into upload-ready Excel files.

## Workflow

1. Put PDF termsheets in `input/`.
2. Add or edit your Excel template at `templates/upload_template.xlsx` or `templates/upload_template.xlsm`.
3. Set `OPENAI_API_KEY` if you want LLM extraction to be preferred over regex extraction.
4. Adjust `schema.py` regexes and the template's `Field Mapping` sheet for your real termsheets and upload template.
5. Run:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

To see available templates:

```bash
python main.py --list-templates
```

To run with a specific template:

```bash
python main.py --template upload_template
python main.py --template bank_b
```

Successful jobs are written to:

```text
output/processed/{pdf_name}_{template_name}_{timestamp}/
```

Each processed folder contains:

- The original PDF
- `product.json`
- The completed Excel workbook

Failed jobs are written to:

```text
output/failed/{pdf_name}_{template_name}_{timestamp}/
```

Each failed folder contains the original PDF and `error.txt`.

## Project Structure

```text
termsheet_uploader/
  input/
  output/
    processed/
    failed/
  templates/
    upload_template.xlsx  # or upload_template.xlsm
    bank_b/
      upload_template.xlsx  # or upload_template.xlsm
  main.py
  config.py
  schema.py
  pdf_extract.py
  parser.py
  excel_writer.py
  template_profiles.py
  template_mapping.py
  fallback_copilot.py
  requirements.txt
```

## Notes

- One PDF is treated as one product.
- No database is used.
- PDF text extraction uses PyMuPDF.
- Excel writing uses openpyxl.
- `excel_writer.py` only handles workbook completion.
- The preferred field-to-cell mapping lives inside the selected template on the `Field Mapping` sheet.
- `template_mapping.py` is only a fallback for templates that do not contain a `Field Mapping` sheet.
- `product.json` records the selected template name and path for traceability.
- `fallback_copilot.py` uses OpenAI when `OPENAI_API_KEY` is set; model-provided values override regex values when present.
- `input/` and `output/` contents are ignored by Git so private termsheets and generated files are not committed.

The runner uses a staging folder under `output/_staging` and only removes an input PDF after the PDF has been safely copied into either `output/processed/` or `output/failed/`.

## Excel Template Mapping

The included `templates/upload_template.xlsx` has two sheets:

- `Upload`: the simple output sheet where parsed values are written.
- `Field Mapping`: the editable map that tells the app where each field should be written.

In `Field Mapping`, edit these columns:

- `field_name`: must match a parser field name, for example `issuer`, `isin`, or `maturity_date`.
- `sheet`: the destination worksheet name.
- `cell`: the destination Excel cell.

For example, this row writes the parsed ISIN into cell `B3` on the `Upload` sheet:

```text
field_name | sheet  | cell
isin       | Upload | B3
```

When the app generates an output workbook, it reads the `Field Mapping` sheet from the template and removes that mapping sheet from the generated file. The original template stays unchanged.

## Multiple Templates

Templates are selected through template profiles. Each `.xlsx` or `.xlsm` file under `templates/` can be used as its own profile.

Common layouts:

```text
templates/
  upload_template.xlsx
  macro_template.xlsm
  bank_b/
    upload_template.xlsx
  bank_macro/
    upload_template.xlsm
```

Profile names:

```text
templates/upload_template.xlsx         -> upload_template
templates/macro_template.xlsm          -> macro_template
templates/bank_b/upload_template.xlsx  -> bank_b/upload_template
templates/bank_macro/upload_template.xlsm -> bank_macro/upload_template
```

For folder templates named `upload_template.xlsx` or `upload_template.xlsm`, you can also use the folder name:

```bash
python main.py --template bank_b
```

Each workbook should carry its own `Field Mapping` sheet, so different templates can write the same parsed fields to completely different sheets and cells. If a workbook does not contain `Field Mapping`, the app falls back to `template_mapping.py`.

Macro-enabled templates are supported with `.xlsm`. When the selected template is `.xlsm`, the app loads it with VBA preservation enabled and writes the generated workbook as `.xlsm`.

If `templates/upload_template.xlsx` is not present but `templates/upload_template.xlsm` is present, the default `python main.py` run uses the `.xlsm` template automatically.
