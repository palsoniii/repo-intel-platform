import { NavLink } from "react-router-dom";
import { Icon } from "./ui";

// The Code tab holds two views of the same thing: the source, and the packages it
// pulls in.
export default function CodeSwitcher() {
  const cls = ({ isActive }: { isActive: boolean }) =>
    `flex h-8 items-center gap-1.5 rounded-md px-3 text-sm font-medium transition ${
      isActive ? "bg-surface text-ink shadow-card" : "text-muted hover:text-ink"
    }`;
  return (
    <div className="inline-flex rounded-lg border border-line bg-sunken p-0.5">
      <NavLink to="../files" className={cls}>
        <Icon name="file" className="h-3.5 w-3.5" /> Files
      </NavLink>
      <NavLink to="../dependencies" className={cls}>
        <Icon name="package" className="h-3.5 w-3.5" /> Packages
      </NavLink>
    </div>
  );
}
