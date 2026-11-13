"""QA-only Excel interoperability check; not used by the deployed application."""
import argparse
from pathlib import Path
from openpyxl import load_workbook

parser=argparse.ArgumentParser()
parser.add_argument('source',type=Path)
parser.add_argument('output',type=Path)
parser.add_argument('--paid',choices=['是','否','待确认'],required=True)
parser.add_argument('--refunded',choices=['是','否','待确认'],required=True)
args=parser.parse_args()
book=load_workbook(args.source)
sheet=book[book.sheetnames[0]]
assert sheet.protection.sheet and sheet.freeze_panes=='A2'
for col in list(range(1,17))+[19]:
 assert sheet.cell(2,col).protection.locked
 assert sheet.cell(2,col).fill.patternType is None
 assert sheet.cell(2,col).font.color.rgb=='FF595959'
for col in [17,18]:
 assert not sheet.cell(2,col).protection.locked
assert any(rule.type=='list' and rule.formula1=='"是,否,待确认"' and rule.errorStyle=='stop' for rule in sheet.data_validations.dataValidation)
assert book.security.lockStructure
sheet['Q2']=args.paid
sheet['R2']=args.refunded
args.output.parent.mkdir(parents=True,exist_ok=True)
book.save(args.output)
book.close()
print('PASS Excel reader/resave: protected unfilled A-P/S with dark-gray text, unlocked Q/R, strict list, row freeze, workbook structure and custom metadata preserved for upload validation.')
