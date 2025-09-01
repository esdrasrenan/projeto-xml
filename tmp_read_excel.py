import pandas as pd
from pathlib import Path
p=Path("data/SIEG.xlsx")
df=pd.read_excel(p)
print('columns=',list(df.columns))
print('rows=',len(df))
print(df.head(10).to_string())
