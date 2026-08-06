# Install tfenv
git clone --depth=1 https://github.com/tfutils/tfenv.git ~/.tfenv
echo 'export PATH="$HOME/.tfenv/bin:$PATH"' >> ~/.bashrc

# Pre-Commit Install
pre-commit install

# Install Google CLI
curl -o ~/google-cloud-cli-linux-x86_64.tar.gz https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-linux-x86_64.tar.gz
tar -xf ~/google-cloud-cli-linux-x86_64.tar.gz -C ~
rm ~/google-cloud-cli-linux-x86_64.tar.gz
~/google-cloud-sdk/install.sh \
  --additional-components terraform-tools \
  --command-completion true \
  --usage-reporting false \
  --path-update true \
  --quiet
