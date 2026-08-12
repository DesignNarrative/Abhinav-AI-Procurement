import json
from app.schemas.document_extraction import DocumentExtractionPayload

def get_extraction_prompt(text: str, model_name: str, document_uuid: str) -> str:
    """
    Generate a highly structured prompt containing the target JSON Schema
    and a complete one-shot example to guide the LLM's structured output.
    """
    schema_json = json.dumps(DocumentExtractionPayload.model_json_schema(), indent=2)

    # A complete one-shot example demonstrating wrapped objects
    example_payload = {
        "document_metadata": {
            "document_id": {
                "value": document_uuid,
                "confidence": 1.0,
                "evidence": "System generated UUID",
                "page_number": 1,
                "bounding_box": None,
                "extraction_method": model_name,
                "validation_status": "UNVALIDATED"
            },
            "document_type": {
                "value": "QUOTATION",
                "confidence": 1.0,
                "evidence": "QUOTATION",
                "page_number": 1,
                "bounding_box": None,
                "extraction_method": model_name,
                "validation_status": "UNVALIDATED"
            },
            "document_number": {
                "value": "EST-7",
                "confidence": 0.95,
                "evidence": "Quotation #: EST-7",
                "page_number": 1,
                "bounding_box": None,
                "extraction_method": model_name,
                "validation_status": "UNVALIDATED"
            },
            "document_date": {
                "value": "2026-06-06",
                "confidence": 0.95,
                "evidence": "Date: 06th June 2026",
                "page_number": 1,
                "bounding_box": None,
                "extraction_method": model_name,
                "validation_status": "UNVALIDATED"
            },
            "revision_number": None,
            "vendor_reference_number": None,
            "total_pages": {
                "value": 1,
                "confidence": 1.0,
                "evidence": "Page 1 of 1",
                "page_number": 1,
                "bounding_box": None,
                "extraction_method": model_name,
                "validation_status": "UNVALIDATED"
            },
            "original_document_path": None
        },
        "vendor_metadata": {
            "vendor_name": {
                "value": "DOT AND LINE",
                "confidence": 0.98,
                "evidence": "DOT AND LINE",
                "page_number": 1,
                "bounding_box": None,
                "extraction_method": model_name,
                "validation_status": "UNVALIDATED"
            },
            "supplier_code": None,
            "gst_number": {
                "value": "27DYKPK8116C1ZE",
                "confidence": 0.98,
                "evidence": "GSTIN 27DYKPK8116C1ZE",
                "page_number": 1,
                "bounding_box": None,
                "extraction_method": model_name,
                "validation_status": "UNVALIDATED"
            },
            "pan_number": {
                "value": "DYKPK8116C",
                "confidence": 0.98,
                "evidence": "GSTIN 27DYKPK8116C1ZE",
                "page_number": 1,
                "bounding_box": None,
                "extraction_method": model_name,
                "validation_status": "UNVALIDATED"
            },
            "billing_address": None,
            "shipping_address": None,
            "contact_person": None,
            "mobile": {
                "value": "8983550088",
                "confidence": 0.95,
                "evidence": "Mobile +91 8983550088",
                "page_number": 1,
                "bounding_box": None,
                "extraction_method": model_name,
                "validation_status": "UNVALIDATED"
            },
            "email": None,
            "bank_account_number": None,
            "bank_ifsc_code": None,
            "bank_name": None
        },
        "project_metadata": {
            "project_name": {
                "value": "Pebbles Business Bay",
                "confidence": 0.90,
                "evidence": "Abhinav Life Spaces LLP Pebble Business Bay wakad",
                "page_number": 1,
                "bounding_box": None,
                "extraction_method": model_name,
                "validation_status": "UNVALIDATED"
            },
            "site_name": None,
            "delivery_location": None
        },
        "commercial_metadata": {
            "currency": {
                "value": "INR",
                "confidence": 1.0,
                "evidence": "Rs.",
                "page_number": 1,
                "bounding_box": None,
                "extraction_method": model_name,
                "validation_status": "UNVALIDATED"
            },
            "payment_terms": None,
            "delivery_terms": None,
            "validity_date": None,
            "delivery_timeline": None,
            "freight_terms": None,
            "loading_unloading_terms": None,
            "insurance_terms": None,
            "warranty_terms": None,
            "total_basic_amount": {
                "value": 15000.0,
                "confidence": 0.95,
                "evidence": "Sub Total 15,000.00",
                "page_number": 1,
                "bounding_box": None,
                "extraction_method": model_name,
                "validation_status": "UNVALIDATED"
            },
            "total_discount_amount": None,
            "total_tax_amount": {
                "value": 2700.0,
                "confidence": 0.95,
                "evidence": "CGST @ 9% 1,350.00 SGST @ 9% 1,350.00",
                "page_number": 1,
                "bounding_box": None,
                "extraction_method": model_name,
                "validation_status": "UNVALIDATED"
            },
            "total_freight_amount": None,
            "total_loading_unloading_amount": None,
            "grand_total_amount": {
                "value": 17700.0,
                "confidence": 0.99,
                "evidence": "Total Rs. 17,700.00",
                "page_number": 1,
                "bounding_box": None,
                "extraction_method": model_name,
                "validation_status": "UNVALIDATED"
            }
        },
        "line_items": [
            {
                "item_index": 1,
                "material_name": {
                    "value": "Mapei Keraflex Maxi S1 White",
                    "confidence": 0.98,
                    "evidence": "Mapei Keraflex Maxi S1 White HSN: 32149090",
                    "page_number": 1,
                    "bounding_box": None,
                    "extraction_method": model_name,
                    "validation_status": "UNVALIDATED"
                },
                "material_id": None,
                "requested_brand": None,
                "offered_brand": {
                    "value": "Mapei",
                    "confidence": 0.95,
                    "evidence": "Mapei Keraflex",
                    "page_number": 1,
                    "bounding_box": None,
                    "extraction_method": model_name,
                    "validation_status": "UNVALIDATED"
                },
                "requested_specification": None,
                "offered_specification": None,
                "quantity": {
                    "value": 50.0,
                    "confidence": 0.98,
                    "evidence": "50 Bag",
                    "page_number": 1,
                    "bounding_box": None,
                    "extraction_method": model_name,
                    "validation_status": "UNVALIDATED"
                },
                "unit_of_measure": {
                    "value": "Bag",
                    "confidence": 0.98,
                    "evidence": "50 Bag",
                    "page_number": 1,
                    "bounding_box": None,
                    "extraction_method": model_name,
                    "validation_status": "UNVALIDATED"
                },
                "basic_rate": {
                    "value": 300.0,
                    "confidence": 0.98,
                    "evidence": "Rate: 300.00",
                    "page_number": 1,
                    "bounding_box": None,
                    "extraction_method": model_name,
                    "validation_status": "UNVALIDATED"
                },
                "discount_percent": None,
                "discount_amount": None,
                "tax_percent": {
                    "value": 18.0,
                    "confidence": 0.95,
                    "evidence": "GST 18%",
                    "page_number": 1,
                    "bounding_box": None,
                    "extraction_method": model_name,
                    "validation_status": "UNVALIDATED"
                },
                "tax_amount": {
                    "value": 2700.0,
                    "confidence": 0.95,
                    "evidence": "2,700.00",
                    "page_number": 1,
                    "bounding_box": None,
                    "extraction_method": model_name,
                    "validation_status": "UNVALIDATED"
                },
                "freight_amount": None,
                "final_landed_rate": {
                    "value": 354.0,
                    "confidence": 0.95,
                    "evidence": "Landed rate: 354",
                    "page_number": 1,
                    "bounding_box": None,
                    "extraction_method": model_name,
                    "validation_status": "UNVALIDATED"
                },
                "total_item_amount": {
                    "value": 17700.0,
                    "confidence": 0.99,
                    "evidence": "Amount: 17,700.00",
                    "page_number": 1,
                    "bounding_box": None,
                    "extraction_method": model_name,
                    "validation_status": "UNVALIDATED"
                },
                "remarks": None
            }
        ],
        "validation_summary": {
            "mathematical_validation": {
                "status": "PASSED",
                "logs": []
            },
            "business_validation": {
                "status": "PASSED",
                "logs": []
            },
            "semantic_validation": {
                "status": "PASSED",
                "logs": []
            }
        },
        "audit_trail": None
    }

    example_json = json.dumps(example_payload, indent=2)

    prompt = f"""
You are an expert AI extraction agent for a procurement system.
Your task is to extract structured information from the raw quotation text or chat transcript below and return a JSON object that strictly conforms to the JSON Schema provided.

JSON Schema:
{schema_json}

To guide your extraction, here is a complete one-shot EXAMPLE of a valid JSON output matching this schema:
{example_json}

Raw Quotation Text/Chat Transcript to extract from:
{text}

CRITICAL RULES:
1. Every field in the schema MUST be a wrapped object containing:
   - "value": The extracted data value (or null if not found in the text).
   - "confidence": Float between 0.0 and 1.0 (estimate how confident you are).
   - "evidence": The exact text snippet from the quotation supporting the value.
   - "page_number": The page number (usually 1).
   - "bounding_box": null
   - "extraction_method": "{model_name}"
   - "validation_status": "UNVALIDATED"
2. Document type is "QUOTATION".
3. Extract all line items and populate the line_items list. For each line item, fields like quantity, basic_rate, unit_of_measure, and total_item_amount MUST be the wrapped objects, NOT null. If they are null, wrap them with a null value key (e.g. "quantity": {{"value": null, "confidence": 0.0, "evidence": "", "page_number": 1, "bounding_box": null, "extraction_method": "{model_name}", "validation_status": "UNVALIDATED"}}).
4. Return ONLY valid, raw JSON. Do not include markdown codeblocks (like ```json), explanations, or any other characters. Start your output with {{ and end it with }}.
5. **List Price & Discount**: If a line item displays a list price (Gross Rate or LP) alongside a discount percentage and a net rate, extract the list price as `basic_rate` and the discount percentage as `discount_percent`. If only a net rate is shown, set `basic_rate` to the net rate and `discount_percent` to 0.
6. **Cartage & Freight Line Items**: Do not extract shipping, transport, freight, cartage, loading, unloading, or packaging as line items. Instead, map their values to the header-level commercial metadata fields (`total_freight_amount`, `total_loading_unloading_amount`) or terms.
7. **Alternative Options**: If items are marked or grouped as options/alternatives, note "Option Item" or "Alternative Item" in their `remarks` field so the Purchase Manager can easily differentiate them.
8. **Specifications**: Retain exact dimensions, thickness, units, and pack sizes (e.g., "12.5mm 6x4", "25 KG", "5kg", "1.5 Kg Part-A") in the `offered_specification` field or as part of the `material_name`.

CHAT TRANSCRIPT ANALYSIS RULES:
- Analyze the entire conversation log from start to finish. Do not ignore earlier messages, as they establish essential context.
- Use information from the start or middle of the chat (such as brand names, delivery locations like Wakad or Bhugaon, and payment terms like RTGS or Advance) to populate the fields of the extracted items.
- Identify the final, active, agreed-upon rates, revisions, and quantities at the culmination of the chat history.
- Map structural steel/materials ranges (e.g., "10-25mm - 46500" and "8/32mm - 47500") as separate line items (e.g., "10-25mm TMT Steel" and "8/32mm TMT Steel").
- Standardize abbreviations: map "Mt", "MT", "pmt", "metric ton" to "MT"; "Bag", "Bags" to "Bags"; and "Nos", "ng", "peice" to "Nos".
"""
    return prompt
