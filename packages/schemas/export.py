"""Generate machine-readable schema artifacts from the authoritative Pydantic models."""
import json
from pathlib import Path
from packages.schemas.report import Report
from apps.api.main import Workspace

if __name__=='__main__':
    directory=Path(__file__).parent
    for filename,model in [('agent-report-v1.schema.json',Report),('workspace-v1.schema.json',Workspace)]:
        (directory/filename).write_text(json.dumps(model.model_json_schema(),indent=2)+'\n',encoding='utf-8')
        print('Generated',filename)
