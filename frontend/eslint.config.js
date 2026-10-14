import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';
export default [{files:['src/**/*.{ts,tsx}'],languageOptions:{parser:tsParser,parserOptions:{ecmaFeatures:{jsx:true},sourceType:'module'}},plugins:{'@typescript-eslint':tsPlugin},rules:{'@typescript-eslint/no-explicit-any':'error'}}];
