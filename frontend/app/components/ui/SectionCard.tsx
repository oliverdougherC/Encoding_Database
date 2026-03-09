import styles from "./SectionCard.module.css";

type Props = {
  title?: string;
  subtitle?: string;
  rightSlot?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
};

export default function SectionCard({ title, subtitle, rightSlot, children, className = "" }: Props) {
  return (
    <section className={`card ${styles.card} ${className}`.trim()}>
      {(title || subtitle || rightSlot) ? (
        <div className={styles.header}>
          <div>
            {title ? <h2 className={styles.title}>{title}</h2> : null}
            {subtitle ? <p className={styles.subtitle}>{subtitle}</p> : null}
          </div>
          {rightSlot ? <div className={styles.right}>{rightSlot}</div> : null}
        </div>
      ) : null}
      <div className={styles.body}>{children}</div>
    </section>
  );
}
