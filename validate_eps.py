"""Optional invocation of the official HL7 FHIR Java validator; requires Java and validator JAR.

Example: python validate_eps.py output/patient_eu_eps.json --validator-jar validator_cli.jar

The IG dependency versions are resolved by the official validator. Internet/package
cache access may be needed to download packages on first run.
"""
from __future__ import annotations
import argparse
import subprocess
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('bundle', type=Path)
    p.add_argument('--validator-jar',type=Path,required=True)
    p.add_argument('--ig', default='hl7.fhir.eu.eps#1.0.0-ballot')
    p.add_argument('--java',default='java')
    args=p.parse_args()
    cmd=[args.java,'-jar',str(args.validator_jar),str(args.bundle),'-version','4.0.1','-ig',args.ig]
    print('Running official HL7 validator:', ' '.join(cmd),flush=True)
    completed=subprocess.run(cmd,check=False)
    raise SystemExit(completed.returncode)

if __name__=='__main__':main()
