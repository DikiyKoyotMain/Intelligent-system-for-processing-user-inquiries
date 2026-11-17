import sys
import shutil
from pathlib import Path

import win32com.client


def export(source, target, update_docx=False):
    source, target = Path(source).resolve(), Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    word = win32com.client.DispatchEx('Word.Application')
    word.Visible = False
    word.DisplayAlerts = 0
    document = None
    try:
        document = word.Documents.Open(str(source), ReadOnly=True, AddToRecentFiles=False)
        document.Fields.Update()
        for table in document.TablesOfContents:
            table.Update()
        document.ExportAsFixedFormat(str(target), 17)
        if update_docx:
            document.SaveAs2(str(target.with_suffix('.docx')), 16)
        print(target)
    finally:
        if document is not None:
            document.Close(False)
        word.Quit()
    if update_docx:
        shutil.copy2(target.with_suffix('.docx'), source)


if __name__ == '__main__':
    export(sys.argv[1], sys.argv[2], '--update-docx' in sys.argv[3:])
