import axios from "axios";

export const api = axios.create({
  baseURL: "/api",
  headers: {
    Authorization: `Bearer ${import.meta.env.VITE_QUERY_TOKEN ?? ""}`,
  },
});
