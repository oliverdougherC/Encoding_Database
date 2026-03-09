import styles from "./EmptyState.module.css";

export default function EmptyState({ title, description }: { title: string; description?: string }) {
  return (
    <div className={styles.empty}>
      <div className={styles.title}>{title}</div>
      {description ? <div className={styles.description}>{description}</div> : null}
    </div>
  );
}
