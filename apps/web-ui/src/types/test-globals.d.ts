// Minimal test globals so tsc can type-check test files without @types/jest
// These are intentionally loose to avoid pulling in extra dependencies.
declare const describe: any;
declare const it: any;
declare const expect: any;
declare const vi: any;
declare const jest: any;
declare const beforeEach: any;
declare const afterEach: any;

// Stub missing graph explorer test import
declare module '../KnowledgeGraphExplorerEnhanced' {
  const Component: any;
  export default Component;
}

declare module '../KnowledgeGraphExplorerEnhanced.tsx' {
  const Component: any;
  export default Component;
}
