import type { SectionCategory } from "../api";

export interface CategoryLeaf {
  key: string;
  name: string;
}

export interface CategoryTreeProps {
  sections: SectionCategory[];
  onPick: (leaf: CategoryLeaf) => void;
}

/** Collapsible sections → groups → leaves of the catalog. */
export function CategoryTree({ sections, onPick }: CategoryTreeProps) {
  return (
    <div className="category-tree">
      {sections.map((section) => (
        <details key={section.key} className="tree-section">
          <summary>{section.name}</summary>
          {section.children.map((group) => (
            <details key={group.key} className="tree-group">
              <summary>{group.name}</summary>
              <ul className="tree-leaves">
                {group.children.map((leaf) => (
                  <li key={leaf.key}>
                    <button
                      type="button"
                      className={leaf.products === 0 ? "tree-leaf empty" : "tree-leaf"}
                      disabled={leaf.products === 0}
                      onClick={() => onPick({ key: leaf.key, name: leaf.name })}
                    >
                      {leaf.name}
                      {leaf.products === 0 && <span className="small muted"> · sin productos</span>}
                    </button>
                  </li>
                ))}
              </ul>
            </details>
          ))}
        </details>
      ))}
    </div>
  );
}
