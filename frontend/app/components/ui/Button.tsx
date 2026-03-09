import styles from "./Button.module.css";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "icon";

type Props = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
};

export default function Button({ variant = "secondary", className = "", type = "button", ...props }: Props) {
  return <button type={type} className={`${styles.button} ${styles[variant]} ${className}`.trim()} {...props} />;
}
