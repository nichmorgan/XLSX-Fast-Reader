import io
import zipfile
from lxml import etree
from pandas import read_csv, to_numeric


class XLSX:
    sheet_xslt = etree.XML('''
        <xsl:stylesheet version="1.0"
            xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
            xmlns:sp="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
            >
            <xsl:output method="text"/>
            <xsl:template match="sp:row">
               <xsl:for-each select="sp:c">
                <xsl:value-of select="parent::*/@r"/> <!-- ROW -->
                <xsl:text>,</xsl:text>
                <xsl:value-of select="@r"/> <!--REMOVEME-->
                <xsl:text>,</xsl:text>
                <xsl:value-of select="@t"/> <!-- TYPE -->
                <xsl:text>,</xsl:text>
                <xsl:value-of select="sp:v/text()"/> <!-- VALUE -->
               <xsl:text>\n</xsl:text>
               </xsl:for-each>
            </xsl:template>
        </xsl:stylesheet>
    ''')

    def __init__(self, file_path):
        self.ns = {
            'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
        }
        self.fh = zipfile.ZipFile(file_path)
        self.shared = self.load_shared()
        self.workbook = self.load_workbook()

    def load_workbook(self):
        # Load workbook
        name = 'xl/workbook.xml'
        root = etree.parse(self.fh.open(name))
        res = {}
        for el in etree.XPath("//ns:sheet", namespaces=self.ns)(root):
            res[el.attrib['name']] = el.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'].replace('rId','')
        return res

    def load_shared(self):
        # Load shared strings
        name = 'xl/sharedStrings.xml'
        root = etree.parse(self.fh.open(name))
        res = etree.XPath("/ns:sst/ns:si/ns:t", namespaces=self.ns)(root)
        return {
            str(pos): el.text
            for pos, el in enumerate(res)
        }

    def _parse_sheet(self, root):
        transform = etree.XSLT(self.sheet_xslt)
        result = transform(root)
        df = read_csv(io.StringIO(str(result)),
                      header=None, dtype=str,
                      names=['row', 'cell', 'type', 'value'],
        )
        return df

    def read(self, sheet_name=0, header=0):
        if type(sheet_name) == int:
            sheet_name = self.workbook.keys()[sheet_name]
            
        sheet_id = self.workbook[sheet_name]
        sheet_path = 'xl/worksheets/sheet%s.xml' % sheet_id
        root = etree.parse(self.fh.open(sheet_path))
        df = self._parse_sheet(root)

        # First row numbers are filled with nan
        df.dropna(subset=["cell"], inplace=True)
        df['row'] = to_numeric(df['row'].fillna(0))

        # Translate string contents
        cond = (df.type == 's') & (~df.value.isnull())
        df.loc[cond, 'value'] = df[cond]['value'].map(self.shared)
        # Add column number and sort rows
        df['col'] = df.cell.str.replace(r'[0-9]+', '')
        df = df.sort_values(by='row')

        # Pivot everything
        df = df.pivot(
            index='row', columns='col', values='value'
        ).reset_index(drop=True).reset_index(drop=True)
        df.columns.name = None  # pivot adds a name to the "columns" array
        # Sort columns (pivot will put AA before B)
        cols = sorted(df.columns, key=lambda x: (len(x), x))
        df = df[cols]
        df = df.dropna(how='all')  # Ignore empty lines
        df = df.dropna(how='all', axis=1)  # Ignore empty cols

        if not header is None:
            if type(header) == list:
                if len(header) == len(df.columns):
                    df.rename({df.columns[i]:str(header[i]) for i in range(len(header))}, inplace=True)
                else:
                    print("[XLSX | read] Could not rename columns because header has invalid size.")
            elif type(header) == int:
                if header in df.index:
                    df.rename(columns={df.columns[i]:df.iloc[header, i] for i in range(len(df.columns))}, inplace=True)
                    df.drop(header, inplace=True)
                    df.reset_index(drop=True, inplace=True)

            else:
                print("[XLSX | read] Could not rename columns because header must be either a list or an index.")

        return df
