import styles from "./ActionStrip.module.css";

type Action = {
  label: string;
  href?: string;
  onClick?: () => void;
  tone?: "primary" | "secondary";
};

export default function ActionStrip({ actions }: { actions: Action[] }) {
  return (
    <div className={styles.strip}>
      {actions.map((action) => {
        const cls = `${styles.action} ${action.tone === "primary" ? styles.primary : styles.secondary}`;
        if (action.href) {
          return (
            <a key={action.label} href={action.href} className={cls}>
              {action.label}
            </a>
          );
        }
        return (
          <button key={action.label} type="button" className={cls} onClick={action.onClick}>
            {action.label}
          </button>
        );
      })}
    </div>
  );
}
