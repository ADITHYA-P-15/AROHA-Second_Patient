import { writeFile } from 'node:fs/promises';
import path from 'node:path';
import openapiTS, { astToString } from 'openapi-typescript';

const ast = await openapiTS(new URL('http://localhost:8000/api/openapi.json'));
const output = path.resolve('src/api/schema.d.ts');
await writeFile(output, astToString(ast), 'utf8');
console.log(`Generated ${output}`);
