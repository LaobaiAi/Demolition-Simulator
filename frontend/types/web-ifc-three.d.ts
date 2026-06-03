/* eslint-disable @typescript-eslint/no-explicit-any */
declare module "web-ifc-three/IFCLoader" {
  export class IFCLoader {
    load(
      url: string,
      onLoad: (model: any) => void,
      onProgress?: (event: { loaded: number; total: number }) => void,
      onError?: (err: Error) => void,
    ): void;
    parse(
      data: string | ArrayBuffer,
      onLoad: (model: any) => void,
    ): void;
    setOnProgress(callback: (event: { loaded: number; total: number }) => void): void;
  }
}
/* eslint-enable @typescript-eslint/no-explicit-any */
