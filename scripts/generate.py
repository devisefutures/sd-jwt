#!/usr/bin/env python3
"""
This utility uses the SD-JWT library to update the static test case data in the
sd_jwt/test_cases directory. It is intended to be run after changes to the
library that affect the test cases.
"""


import argparse
import logging
import sys
from pathlib import Path

from sd_jwt import __version__
from sd_jwt.holder import SDJWTHolder
from sd_jwt.issuer import SDJWTIssuer
from sd_jwt.utils.demo_utils import get_jwk, load_yaml_example, load_yaml_settings
from sd_jwt.verifier import SDJWTVerifier

from sd_jwt.utils import formatting

logger = logging.getLogger("sd_jwt")

# Set logging to stdout
logging.basicConfig(stream=sys.stdout, level=logging.INFO)


def generate_test_case_data(testcase_path: Path, type: str):
    seed = settings["random_seed"]
    demo_keys = get_jwk(settings["key_settings"], True, seed)

    ### Load test case data
    testcase = load_yaml_example(testcase_path)
    use_decoys = testcase.get("add_decoy_claims", False)

    claims = {
        "iss": settings["identifiers"]["issuer"],
        "iat": settings["iat"],
        "exp": settings["exp"],
    }

    claims.update(testcase["user_claims"])

    ### Produce SD-JWT and SVC for selected example
    SDJWTIssuer.unsafe_randomness = True
    sdjwt_at_issuer = SDJWTIssuer(
        claims,
        demo_keys["issuer_key"],
        demo_keys["holder_key"] if testcase.get("holder_binding", False) else None,
        add_decoy_claims=use_decoys,
    )

    ### Produce SD-JWT-R for selected example

    sdjwt_at_holder = SDJWTHolder(sdjwt_at_issuer.combined_sd_jwt_iid)
    sdjwt_at_holder.create_presentation(
        testcase["holder_disclosed_claims"],
        settings["holder_binding_nonce"]
        if testcase.get("holder_binding", False)
        else None,
        settings["identifiers"]["verifier"]
        if testcase.get("holder_binding", False)
        else None,
        demo_keys["holder_key"] if testcase.get("holder_binding", False) else None,
    )

    ### Verify the SD-JWT using the SD-JWT-R

    # Define a function to check the issuer and retrieve the
    # matching public key
    def cb_get_issuer_key(issuer):
        # Do not use in production - this allows to use any issuer name for demo purposes
        if issuer == claims["iss"]:
            return demo_keys["issuer_public_key"]
        else:
            raise Exception(f"Unknown issuer: {issuer}")

    sdjwt_at_verifier = SDJWTVerifier(
        sdjwt_at_holder.combined_presentation,
        cb_get_issuer_key,
        settings["identifiers"]["verifier"]
        if testcase.get("holder_binding", False)
        else None,
        settings["holder_binding_nonce"]
        if testcase.get("holder_binding", False)
        else None,
    )
    verified = sdjwt_at_verifier.get_verified_payload()

    # Write the test case data to the directory of the test case

    _artifacts = {
        "user_claims": (testcase["user_claims"], "User Claims", "json"),
        "sd_jwt_payload": (
            sdjwt_at_issuer.sd_jwt_payload,
            "Payload of the SD-JWT",
            "json",
        ),
        "sd_jwt_serialized": (
            sdjwt_at_issuer.serialized_sd_jwt,
            "Serialized SD-JWT",
            "txt",
        ),
        "combined_issuance": (
            sdjwt_at_issuer.combined_sd_jwt_iid,
            "Combined SD-JWT and Disclosures",
            "txt",
        ),
        "hb_jwt_payload": (
            sdjwt_at_holder.holder_binding_jwt_payload
            if testcase.get("holder_binding")
            else None,
            "Payload of the Holder Binding JWT",
            "json",
        ),
        "hb_jwt_serialized": (
            sdjwt_at_holder.serialized_holder_binding_jwt,
            "Serialized Holder Binding JWT",
            "txt",
        ),
        "combined_presentation": (
            sdjwt_at_holder.combined_presentation,
            "Combined representation of SD-JWT and HS-Disclosures",
            "txt",
        ),
        "verified_contents": (
            verified,
            "Verified released contents of the SD-JWT",
            "json",
        ),
    }

    # When type is example, add info about disclosures
    if type == "example":
        _artifacts["disclosures"] = (
            formatting.markdown_disclosures(
                sdjwt_at_holder._hash_to_decoded_disclosure,
                sdjwt_at_holder._hash_to_disclosure,
            ),
            "Payloads of the II-Disclosures",
            "md",
        )

    # When decoys were used, list those as well (here as a json array)
    if use_decoys:
        if type == "example":
            _artifacts["decoy_digests"] = (
                formatting.markdown_decoy_digests(sdjwt_at_issuer.decoy_digests),
                "Decoy Claims",
                "md",
            )
        else:
            _artifacts["decoy_digests"] = (
                sdjwt_at_issuer.decoy_digests,
                "Decoy Claims",
                "json",
            )

    output_dir = testcase_path.parent

    logger.info(f"Writing test case data to '{output_dir}'.")

    if not output_dir.exists():
        sys.exit(f"Output directory '{output_dir}' does not exist.")

    formatter = (
        formatting.format_for_example
        if type == "example"
        else formatting.format_for_testcase
    )

    for key, data_item in _artifacts.items():
        if data_item is None:
            continue

        data, _, ftype = data_item

        with open(output_dir / f"{key}.{ftype}", "w") as f:
            f.write(formatter(data, ftype))


# For all *.yml files in subdirectories of the working directory, run the test case generation
if __name__ == "__main__":
    # This tool must be called with either "testcase" or "example" as the first argument in order
    # to specify which type of output to generate.

    parser = argparse.ArgumentParser(
        description=(
            "Generate test cases or examples for SD-JWT library. "
            "Test case data is suitable for use in other SD-JWT libraries. "
            "Examples are formatted in a markdown-friendly way (e.g., line breaks, "
            "markdown formatting) for direct inclusion into the specification text."
        )
    )

    # Type is a positional argument, either testcase or example
    parser.add_argument(
        "type",
        choices=["testcase", "example"],
        help="Whether to generate test cases or examples.",
    )

    # Optional: One or more names of directories containing test cases to generate
    parser.add_argument(
        "directories",
        nargs="*",
        help=(
            "One or more names of directories containing test cases to generate. "
            "If no directories are specified, all directories containing a file "
            "named 'specification.yml' respectively are processed."
        ),
    )
    args = parser.parse_args()

    basedir = Path.cwd()
    settings_file = basedir / "settings.yml"

    if not settings_file.exists():
        sys.exit(f"Settings file '{settings_file}' does not exist.")

    if args.directories:
        glob = [basedir / d / "specification.yml" for d in args.directories]
    else:
        glob = basedir.glob("*/specification.yml")

    # load keys and other information from test_settings.yml
    settings = load_yaml_settings(settings_file)

    for case_path in glob:
        logger.info(f"Generating data for '{case_path}'")
        generate_test_case_data(case_path, args.type)
