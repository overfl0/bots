import asyncio
import logging
import os
import platform
import subprocess

from discord.ext import commands

import checks
import settings

logger = logging.getLogger('discord.' + __name__)


class FancyProgress:
    def __init__(self):
        self.messages = []

    def next_state(self, state):
        self.messages.append(state)
        return self  # So that we can chain calls

    def __str__(self):
        return '```\n' + '\n'.join(self.messages) + '```'


class Rebuilder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def git_pull(self, branch='master'):
        remote_branch = branch if '/' in branch else 'origin/{}'.format(branch)

        # Note: this is the 100% correct way of safely updating a repository
        update_commands = [
            ['git', 'reset', '--hard'],
            ['git', 'fetch', '--all'],
            ['git', 'checkout', branch],
            ['git', 'reset', '--hard', remote_branch],
            ['git', 'pull'],
        ]

        for command in update_commands:
            logger.info('Running: %s', ' '.join(command))
            subprocess.run(command, check=True, cwd=settings.VMPATH)

    def call_cmake(self):
        new_env = dict(os.environ, **settings.BUILD_ENV)  # Add envs just for this command
        subprocess.run(['cmake', '.'], check=True, cwd=settings.VMPATH, env=new_env)

    def build_sqfvm(self):
        command =['cmake', '--build', '.', '--target', 'libcsqfvm']

        # msbuild on Windows is already doing parallel building
        # and adding the "parallel" switch actually PREVENTS from doing that
        if platform.system() == 'Linux':
            command.extend(['--parallel', '6'])

        subprocess.run(command, check=True, cwd=settings.VMPATH)


    @commands.command()
    @checks.only_admins()
    async def rebuild(self, ctx):
        """Update and rebuild SQF-VM"""
        progress = FancyProgress()

        async def _run_asynchronously(message_text, sync_function, *sync_args):
            """Small wrapper to better call synchronous shell commands
            Updates the message and executes a command in an executor
            """
            await message.edit(content=progress.next_state(message_text))
            try:
                await asyncio.get_event_loop().run_in_executor(None, sync_function, *sync_args)
            except Exception as e:
                logger.exception('%s', e)
                await message.edit(content=progress.next_state('Error: ' + str(e)))
                return False
            return True

        message = await ctx.channel.send(progress.next_state('Unloading SQF-VM...'))

        try:
            async with ctx.typing():
                self.bot.sqfvm.unload()

                # git pull
                if not await _run_asynchronously('Pulling changes...', self.git_pull):
                    return

                # rm CMakeCache.txt
                await message.edit(content=progress.next_state('Deleting CmakeCache.txt'))
                try:
                    os.remove(os.path.join(settings.VMPATH, 'CMakeCache.txt'))
                except FileNotFoundError:
                    pass

                # cmake .
                if not await _run_asynchronously('Running cmake...', self.call_cmake):
                    return

                # make libsqfvm
                if not await _run_asynchronously('Building...', self.build_sqfvm):
                    return

                await message.edit(content=progress.next_state('Loading SQF-VM...'))
                self.bot.sqfvm.load()

                if self.bot.sqfvm.ready():
                    await message.edit(content=progress.next_state('SQF-VM is ready!'))

        except Exception as e:
            logger.exception('%s', e)
            await message.edit(content=progress.next_state('Error: ' + str(e)))
            await ctx.channel.send('SQF-VM has NOT been rebuilt correctly!')
        else:
            await ctx.channel.send('SQF-VM has been rebuilt!')


def setup(bot):
    bot.add_cog(Rebuilder(bot))
