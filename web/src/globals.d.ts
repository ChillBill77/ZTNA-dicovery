// React 19 + @types/react 19 dropped the implicit global `JSX` namespace —
// `JSX.Element` references in our existing components/tests don't resolve
// without an explicit shim. Re-export React's JSX types under the legacy
// global name so the codebase compiles unchanged.
import type { JSX as ReactJSX } from "react";

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    type Element = ReactJSX.Element;
    type IntrinsicElements = ReactJSX.IntrinsicElements;
    type ElementClass = ReactJSX.ElementClass;
    type ElementAttributesProperty = ReactJSX.ElementAttributesProperty;
    type ElementChildrenAttribute = ReactJSX.ElementChildrenAttribute;
    type LibraryManagedAttributes<C, P> = ReactJSX.LibraryManagedAttributes<C, P>;
  }
}

export {};
