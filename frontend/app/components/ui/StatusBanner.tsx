import styles from "./StatusBanner.module.css";

type Kind = "error" | "warning" | "success" | "info";

type Props = {
  kind?: Kind;
  children: React.ReactNode;
  className?: string;
};

export default function StatusBanner({ kind = "info", children, className = "" }: Props) {
  return <div className={`${styles.banner} ${styles[kind]} ${className}`.trim()}>{children}</div>;
}
