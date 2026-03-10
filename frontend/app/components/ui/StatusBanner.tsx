import styles from "./StatusBanner.module.css";

type Kind = "error" | "warning" | "success" | "info";

type Props = {
  kind?: Kind;
  children: React.ReactNode;
  className?: string;
};

export default function StatusBanner({ kind = "info", children, className = "" }: Props) {
  const isAssertive = kind === "error" || kind === "warning";
  return (
    <div
      className={`${styles.banner} ${styles[kind]} ${className}`.trim()}
      role={isAssertive ? "alert" : "status"}
      aria-live={isAssertive ? "assertive" : "polite"}
      aria-atomic="true"
    >
      {children}
    </div>
  );
}
