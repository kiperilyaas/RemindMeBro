// Images imported by the components are inlined into the single-file builds.
declare module "*.png" {
  const src: string;
  export default src;
}
