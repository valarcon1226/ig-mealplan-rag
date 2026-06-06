import { IgApiClient } from "instagram-private-api";

async function test() {
   const ig = new IgApiClient();
   console.log(ig.feed);
}
test();


